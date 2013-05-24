# coding=utf8
import sublime, sublime_plugin
import codecs
import sys
import os
from .chardet.universaldetector import UniversalDetector
import re
import threading
import time

# don't parse binary files, just mark these as binary
BINARY = re.compile('\.(apng|png|jpg|gif|jpeg|bmp|psd|ai|cdr|ico|cache|sublime-package|eot|svgz|ttf|woff|zip|tar|gz|rar|bz2|jar|xpi|mov|mpeg|avi|mpg|flv|wmv|mp3|wav|aif|aiff|snd|wma|asf|asx|pcm|pdf|doc|docx|xls|xlsx|ppt|pptx|rtf|sqlite|sqlitedb|fla|swf|exe)$', re.I);

def plugin_loaded():
	global s, Pref
	s = sublime.load_settings('EncodingHelper.sublime-settings')
	Pref = Pref()
	Pref.load();
	s.add_on_change('reload', lambda:Pref.load())

class Pref:
	def load(self):
		Pref.show_encoding_on_status_bar = bool(s.get('show_encoding_on_status_bar', True))

		encoding_list = []
		for encoding in s.get('fallback_encodings', []):
			if encoding != '':
				encoding_list.append(encoding.upper())
		Pref.fallback_encodings = encoding_list
		if not Pref.fallback_encodings:
			Pref.fallback_encodings = ["UTF-8", "ISO-8859-1", 'SHIFT-JIS', 'WINDOWS-1252', 'GBK', 'WINDOWS-1256'];

		open_automatically_as_utf8 = []
		for encoding in s.get('open_automatically_as_utf8', []):
			if encoding != '':
				open_automatically_as_utf8.append(encoding.upper())
		Pref.open_automatically_as_utf8 = open_automatically_as_utf8

class EncodingOnStatusBarListener(sublime_plugin.EventListener):

	# this function is called to update the statusbar
	# we need to know wich encoding ST is giving to the file in order to tell: "document maybe broken"
	# we compare the detected encoding of this package with the detected encoding by ST
	def on_encodings_detected(self, v, ok = True):
		# we give time to ST to "detect" or use the "fallback encoding".
		if v.encoding() == 'Undefined' and ok:
			sublime.set_timeout(lambda:self.on_encodings_detected(v, False), 250)
			return
		elif v.encoding() == 'Undefined' and not ok:
			v.settings().set('encoding_helper_encoding_ST', 'UTF-8')
		# ok, sublime was able to set some encoding to this file
		else:
			v.settings().set('encoding_helper_encoding_ST', v.encoding())

		# here code, "document maybe broken"
		encoding_sublime = v.settings().get('encoding_helper_encoding_ST')
		encoding_encohelp = v.settings().get('encoding_helper_encoding') or ''
		encoding_converted = v.settings().get('encoding_helper_converted') or ''

		if encoding_sublime == 'Hexadecimal' and encoding_encohelp == 'BINARY':
			encoding_encohelp = ''

		if encoding_converted != None and encoding_converted:
			v.set_status('encoding_helper_statusbar', "Converted to UTF-8 from "+encoding_converted)
		elif encoding_sublime.replace(' ', '').replace('-', '').replace('_', '').lower().strip() != encoding_encohelp.replace(' ', '').replace('-', '').replace('_', '').lower().strip() and encoding_encohelp != '' and encoding_encohelp != 'Unknown' and encoding_encohelp != 'Detecting encoding…':
			v.set_status('encoding_helper_statusbar', 'Opened as '+encoding_sublime+', detected '+encoding_encohelp+' (document maybe broken)')
		else:
			v.set_status('encoding_helper_statusbar', encoding_sublime)

	# sublime may knows the encoding of the loaded file at on_load time
	def on_load(self, v):
		if not v.settings().get('is_widget'):
			self.on_encodings_detected(v);

	def on_post_save_async(self, v):
		if not v.settings().get('is_widget'):
			v.settings().erase('encoding_helper_converted')
			v.settings().erase('encoding_helper_encoding')
			self.on_load_async(v);

	def on_activated_async(self, v):
		if not v.settings().get('is_widget'):
			#v.settings().erase('encoding_helper_encoding')
			self.on_load_async(v);

	# try to guess the encoding
	def on_load_async(self, v):
		if not v or v.settings().get('is_widget'):
			return

		# if enabled, show encoding on status bar
		if Pref.show_encoding_on_status_bar:

			#has cached state?
			if v.settings().has('encoding_helper_encoding'):
				self.on_encodings_detected(v);
			else:
				v.settings().set('encoding_helper_encoding', '')

				# if the file is not there, just give up
				file_name = v.file_name()
				if not file_name or file_name == '' or os.path.isfile(file_name) == False:
					self.on_encodings_detected(v);
				#guess
				else:
					v.settings().set('encoding_helper_encoding', 'Detecting encoding…')
					v.set_status('encoding_helper_statusbar', 'Detecting encoding…');

					confidence = 0
					size = os.stat(file_name).st_size
					if BINARY.search(file_name):
						encoding = 'BINARY'
						confidence = 1
					elif size > 1048576 and maybe_binary(file_name):
						encoding = 'BINARY'
						confidence = 0.7
					elif maybe_binary(file_name):
						encoding = 'BINARY'
						confidence = 0.7
					elif size > 1048576: # skip files > 1Mb
						encoding = 'Unknown'
						confidence = 1
					else:
						fallback_processed = False
						fallback = False
						encoding = ''

						if size < 666:
							fallback = test_fallback_encodings(v, file_name)
							fallback_processed = True
							if fallback != False:
								encoding = fallback
						if not encoding:
							detector = UniversalDetector()
							fp = open(file_name, 'rb')
							detector.feed(fp.read())
							fp.close()
							detector.close()

							if detector.done:
								encoding = str(detector.result['encoding']).upper()
								confidence = detector.result['confidence']
							else:
								encoding = 'Unknown'
								confidence = 1
							del detector
						if encoding == None or encoding == 'NONE' or encoding == '' or encoding == 'Unknown' or confidence < 0.7:
							if not fallback_processed:
								fallback = test_fallback_encodings(v, file_name)
							if fallback != False:
								encoding = fallback


					if v:
						if encoding == 'ASCII':
							encoding = 'UTF-8'
						if encoding != '' and encoding != 'UTF-8' and encoding in Pref.open_automatically_as_utf8 and v.is_dirty() == False:
							ConvertToUTF8(v, file_name, encoding).start()
						elif v:
							v.settings().set('encoding_helper_encoding', encoding)
							self.on_encodings_detected(v);

class Toutf8fromBestGuessCommand(sublime_plugin.WindowCommand):

	def run(self):
		encoding = sublime.active_window().active_view().settings().get('encoding_helper_encoding')
		if encoding != None and encoding != 'UTF-8' and encoding != 'BINARY' and encoding != 'Unknown' and encoding != '' and encoding != 'Detecting encoding…':
			Toutf8fromCommand(sublime_plugin.WindowCommand).run(encoding)

	def description(self):
		try:
			encoding = sublime.active_window().active_view().settings().get('encoding_helper_encoding')
			if encoding != None and encoding != 'UTF-8' and encoding != 'BINARY' and encoding != 'Unknown' and encoding != '' and encoding != 'Detecting encoding…':
				return 'Convert to UTF-8 From '+encoding
			else:
				return 'Convert to UTF-8 From Best Guess'
		except:
			return 'Convert to UTF-8 From Best Guess'

	def is_enabled(self):
		try:
			encoding = sublime.active_window().active_view().settings().get('encoding_helper_encoding')
			if encoding != None and encoding != 'UTF-8' and encoding != 'BINARY' and encoding != 'Unknown' and encoding != '' and encoding != 'Detecting encoding…':
				return True
			else:
				return False
		except:
			return False

class Toutf8fromCommand(sublime_plugin.WindowCommand):

	def run(self, encoding = ''):
		try:
			if encoding == None or encoding == 'UTF-8' or encoding == 'BINARY' or encoding == 'Unknown' or encoding == '' or encoding == 'Detecting encoding…':
				return False
			v = sublime.active_window().active_view()
			file_name = v.file_name()
			if not file_name or file_name == '' or os.path.isfile(file_name) == False:
				return False
			else:
				ConvertToUTF8(v, file_name, encoding).start()
				return True
		except:
			return False

	def is_enabled(self, encoding = ''):
		try:
			file_name = sublime.active_window().active_view().file_name()
			if not file_name or file_name == '' or os.path.isfile(file_name) == False:
				return False
			else:
				return True
		except:
			return False

class ConvertToUTF8(threading.Thread):

	def __init__(self, v, file_name, encoding, callback = False):

		threading.Thread.__init__(self)

		self.file_name = file_name
		self.encoding = encoding
		self.v = v
		if callback == False:
			self.callback = self.on_done
		else:
			self.callback = callback

	def run(self):
		_encoding = self.encoding.lower()
		try:
			content = codecs.open(self.file_name, "rb", _encoding, errors='strict').read()
			if len(content) != 0:
				sublime.set_timeout(lambda:self.callback(content, self.encoding), 0)
		except LookupError:
			sublime.set_timeout(lambda:self.on_lookup_error(self.file_name, self.encoding), 0)
		except:
			sublime.set_timeout(lambda:self.on_error(self.file_name, self.encoding), 0)

	def on_done(self, content, encoding):
		if self.v:
			write_to_view(self.v, content);
			self.v.settings().set('encoding_helper_converted', encoding)
			self.v.settings().set('encoding_helper_encoding', 'UTF-8')
			EncodingOnStatusBarListener().on_encodings_detected(self.v);

	def on_error(self, file_name, encoding):
		self.v.settings().set('encoding_helper_encoding', encoding)
		EncodingOnStatusBarListener().on_encodings_detected(self.v);
		sublime.error_message('Unable to convert to UTF-8 from encoding "'+encoding+'" the file: \n'+file_name);

	def on_lookup_error(self, file_name, encoding):
		self.v.settings().set('encoding_helper_encoding', encoding)
		EncodingOnStatusBarListener().on_encodings_detected(self.v);
		sublime.error_message('The encoding "'+encoding+'" is unknown in this system.\n Unable to convert to UTF-8 the file: \n'+file_name);

def maybe_binary(file_name):
	fp = open(file_name, 'rb')
	line = fp.read(500);
	read = 500
	null_char = '\x00'.encode();
	while line != '':
		if null_char in line:
			fp.close()
			return True
		read += 8000
		if read > 1048576:
			fp.close()
			return False
		line = fp.read(8000)
	fp.close()
	return False

def test_fallback_encodings(v, file_name, encodings = False):
	if encodings == False:
		encodings = Pref.fallback_encodings
	for encoding in encodings:
		_encoding = encoding.lower()
		try:
			fp = codecs.open(file_name, "rb", _encoding, errors='strict')
			content = fp.read();
			fp.close()
			return encoding
		except UnicodeDecodeError:
			fp.close()
	return False

def write_to_view(view, content):
	view.run_command('encoding_helper_write_to_view', {"content": content});
class EncodingHelperWriteToViewCommand(sublime_plugin.TextCommand):
	def run(self, edit, content):
		view = self.view
		view.replace(edit, sublime.Region(0, view.size()), content);
		view.sel().clear()
		view.sel().add(sublime.Region(0))
		view.end_edit(edit)