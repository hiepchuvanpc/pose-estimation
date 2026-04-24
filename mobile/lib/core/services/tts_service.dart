import 'package:flutter_tts/flutter_tts.dart';

/// Text-to-speech service using platform TTS.
///
/// Android: TextToSpeech API
/// iOS: AVSpeechSynthesizer
class TtsService {
  final FlutterTts _tts = FlutterTts();
  bool _isReady = false;
  final List<String> _queue = [];
  bool _isSpeaking = false;

  Future<void> initialize() async {
    await _tts.setLanguage('vi-VN');
    await _tts.setSpeechRate(0.5);
    await _tts.setVolume(1.0);
    await _tts.setPitch(1.0);

    _tts.setCompletionHandler(() {
      _isSpeaking = false;
      _processQueue();
    });

    _isReady = true;
  }

  /// Speak text with priority queueing.
  ///
  /// Priority 1 (highest): Safety/pose warnings
  /// Priority 2: Set/exercise transitions
  /// Priority 3 (lowest): Rep counting
  Future<void> speak(String text, {int priority = 2}) async {
    if (!_isReady) return;

    if (priority <= 1 && _isSpeaking) {
      // High priority: interrupt current speech
      await _tts.stop();
      _isSpeaking = false;
      _queue.clear();
    }

    _queue.add(text);
    _processQueue();
  }

  void _processQueue() {
    if (_isSpeaking || _queue.isEmpty) return;
    _isSpeaking = true;
    final text = _queue.removeAt(0);
    _tts.speak(text);
  }

  /// Stop all speech.
  Future<void> stop() async {
    _queue.clear();
    _isSpeaking = false;
    await _tts.stop();
  }

  Future<void> dispose() async {
    await _tts.stop();
  }
}
