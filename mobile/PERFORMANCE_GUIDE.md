# 🚀 HƯỚNG DẪN TỐI ƯU HIỆU NĂNG - MOTION COACH APP

## Tổng quan

Đã implement các tối ưu hiệu năng sau:

---

## 1. Battery-Aware Processing

**File**: `lib/core/utils/performance_optimizer.dart`

### PerformanceOptimizer
- Tự động điều chỉnh chất lượng dựa trên pin
- 3 mức: High (>50% hoặc đang sạc), Medium (20-50%), Low (<20%)

```dart
final optimizer = PerformanceOptimizer();
await optimizer.initialize();

// Get recommended settings
final quality = optimizer.getRecommendedQuality();
final frameRate = optimizer.getRecommendedFrameRate();
final frameSkip = optimizer.getFrameSkipCount();

// Check if should process
if (optimizer.shouldAllowVideoProcessing()) {
  // Do heavy processing
}
```

### ProcessingQuality
| Level | Frame Rate | Frame Skip | Description |
|-------|------------|------------|-------------|
| High | 30 FPS | 1 | Full quality |
| Medium | 15 FPS | 2 | Balanced |
| Low | 10 FPS | 3 | Power save |

---

## 2. Pose Detection Throttling

**File**: `lib/core/utils/rate_limiters.dart`

### Throttler
- Giới hạn tần suất xử lý pose detection
- Tránh overload CPU

```dart
final throttler = Throttler(interval: Duration(milliseconds: 66)); // ~15 FPS

_cameraController.startImageStream((image) {
  throttler.run(() {
    _processPoseDetection(image);
  });
});
```

### Debouncer
- Delay action cho đến khi user ngừng input

```dart
final debouncer = Debouncer(delay: Duration(milliseconds: 300));

searchController.addListener(() {
  debouncer.run(() {
    searchExercises(searchController.text);
  });
});
```

### RateLimiter
- Giới hạn số lượng calls trong time window

```dart
final limiter = RateLimiter(maxCalls: 10, window: Duration(seconds: 1));

if (limiter.tryCall()) {
  // Process
} else {
  // Wait or skip
}
```

---

## 3. Image Caching

**File**: `lib/core/utils/image_cache_manager.dart`

### ImageCacheManager
- LRU cache cho thumbnails
- Max 50 items
- Auto-expire sau 30 phút

```dart
final cache = ImageCacheManager();

// Get cached image
final cached = cache.get('exercise_123_thumb');
if (cached != null) {
  // Use cached.bytes
} else {
  final bytes = await loadThumbnail('exercise_123');
  cache.put('exercise_123_thumb', bytes);
}
```

---

## 4. Lazy Loading Lists

**File**: `lib/shared/widgets/lazy_loading_list.dart`

### LazyLoadingList
- Pagination với infinite scroll
- Pull-to-refresh
- Auto load more khi scroll gần cuối

```dart
LazyLoadingList<Exercise>(
  pageSize: 20,
  loadPage: (page, pageSize) async {
    return await repository.getExercises(page: page, limit: pageSize);
  },
  itemBuilder: (context, exercise, index) {
    return ExerciseCard(exercise: exercise);
  },
)
```

### LazyLoadingGrid
- Same như list nhưng dạng grid

```dart
LazyLoadingGrid<Exercise>(
  crossAxisCount: 2,
  loadPage: (page, pageSize) => loadExercises(page, pageSize),
  itemBuilder: (context, item, index) => ExerciseCard(exercise: item),
)
```

---

## 5. Memory Management

**File**: `lib/core/utils/performance_optimizer.dart`

### MemoryManager
- Track memory usage
- Enforce limits
- GC hints

```dart
final memoryManager = MemoryManager();

if (memoryManager.canAllocate(videoSizeBytes)) {
  // Allocate buffer
  memoryManager.track(buffer, videoSizeBytes);
} else {
  // Wait or reduce quality
}
```

### DiskSpaceChecker
- Check disk space trước khi record

```dart
if (await DiskSpaceChecker.hasSpaceForRecording(durationSeconds: 300)) {
  // Start recording
}
```

---

## 6. Workout Screen Optimizations

**File**: `lib/features/workout/workout_screen.dart`

Đã apply:
- Battery-aware camera resolution
- Frame skipping based on battery
- Throttled pose detection
- Lazy image stream processing

```dart
// Dynamic resolution based on battery
final quality = _performanceOptimizer.getRecommendedQuality();
final resolution = quality == ProcessingQuality.high
    ? ResolutionPreset.high
    : quality == ProcessingQuality.medium
        ? ResolutionPreset.medium
        : ResolutionPreset.low;

// Frame skipping
_frameCount++;
if (_frameCount % _frameSkipCount != 0) return;
```

---

## 7. Build Optimizations

### R8/ProGuard (Release builds)
- Code shrinking
- Obfuscation
- Dead code elimination

**File**: `android/app/build.gradle.kts`
```kotlin
release {
    isMinifyEnabled = true
    isShrinkResources = true
}
```

### Resource Exclusions
```kotlin
packaging {
    resources {
        excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}
```

---

## 8. Best Practices Applied

### Dispose Resources
```dart
@override
void dispose() {
  _cameraController?.dispose();
  _poseService.dispose();
  _throttler.dispose();
  super.dispose();
}
```

### Isolate Heavy Work
```dart
// For CPU-intensive tasks
await compute(heavyFunction, argument);
```

### Avoid Rebuilds
- Use `const` widgets
- Use `ValueListenableBuilder` for fine-grained updates
- Cache computed values

---

## 📊 Metrics to Monitor

| Metric | Target | Tool |
|--------|--------|------|
| FPS | 60 | Flutter DevTools |
| Memory | <200MB | DevTools Memory |
| Battery | <5%/hour | Android Profiler |
| Startup | <2s | Trace |
| Pose latency | <50ms | Custom logging |

---

## 🔧 Debugging Performance

```bash
# Run with profile mode
flutter run --profile

# Analyze APK size
flutter build apk --analyze-size

# Check for jank
flutter run --trace-skia
```

---

## ✅ Checklist

- [x] Battery-aware processing
- [x] Pose detection throttling
- [x] Image caching
- [x] Lazy loading widgets
- [x] Memory management
- [x] R8/ProGuard enabled
- [x] Resource cleanup
- [ ] Startup optimization
- [ ] Network caching
- [ ] Background work optimization
