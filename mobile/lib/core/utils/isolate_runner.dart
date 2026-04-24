import 'dart:async';
import 'dart:isolate';

import 'package:flutter/foundation.dart';

/// Utility để chạy heavy computation trong isolate
class IsolateRunner {
  /// Run function trong isolate riêng
  static Future<R> run<R>(FutureOr<R> Function() computation) {
    return compute((_) => computation(), null);
  }

  /// Run function với single argument trong isolate
  static Future<R> runWithArg<T, R>(
    FutureOr<R> Function(T arg) computation,
    T arg,
  ) {
    return compute(computation, arg);
  }

  /// Run heavy JSON parsing trong isolate
  static Future<T> parseJson<T>(
    String jsonString,
    T Function(Map<String, dynamic>) fromJson,
  ) {
    return compute(
      (String json) {
        // Note: This is a simplified placeholder - actual JSON parsing
        // would need proper implementation with dart:convert
        return fromJson(<String, dynamic>{});
      },
      jsonString,
    );
  }
}

/// Pool of reusable isolates for frequent operations
class IsolatePool {
  final int size;
  final List<Isolate> _isolates = [];
  final List<SendPort> _sendPorts = [];
  final List<bool> _available = [];
  bool _initialized = false;

  IsolatePool({this.size = 2});

  /// Initialize the pool
  Future<void> initialize() async {
    if (_initialized) return;

    for (int i = 0; i < size; i++) {
      final receivePort = ReceivePort();
      final isolate = await Isolate.spawn(
        _isolateEntryPoint,
        receivePort.sendPort,
      );
      
      final sendPort = await receivePort.first as SendPort;
      
      _isolates.add(isolate);
      _sendPorts.add(sendPort);
      _available.add(true);
    }

    _initialized = true;
  }

  /// Run task in available isolate
  Future<R> run<T, R>(R Function(T) task, T arg) async {
    if (!_initialized) {
      await initialize();
    }

    // Find available isolate
    final index = _available.indexWhere((a) => a);
    if (index == -1) {
      // No available isolate, run inline
      return task(arg);
    }

    _available[index] = false;
    
    try {
      final responsePort = ReceivePort();
      _sendPorts[index].send([task, arg, responsePort.sendPort]);
      final result = await responsePort.first;
      return result as R;
    } finally {
      _available[index] = true;
    }
  }

  /// Shutdown all isolates
  void dispose() {
    for (final isolate in _isolates) {
      isolate.kill(priority: Isolate.immediate);
    }
    _isolates.clear();
    _sendPorts.clear();
    _available.clear();
    _initialized = false;
  }

  static void _isolateEntryPoint(SendPort sendPort) {
    final receivePort = ReceivePort();
    sendPort.send(receivePort.sendPort);

    receivePort.listen((message) {
      final task = message[0] as Function;
      final arg = message[1];
      final replyPort = message[2] as SendPort;

      try {
        final result = task(arg);
        replyPort.send(result);
      } catch (e) {
        replyPort.send(null);
      }
    });
  }
}
