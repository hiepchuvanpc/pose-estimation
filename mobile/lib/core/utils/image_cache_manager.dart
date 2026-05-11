/// Image cache để tái sử dụng thumbnails và images
class ImageCacheManager {
  static final ImageCacheManager _instance = ImageCacheManager._internal();
  factory ImageCacheManager() => _instance;
  ImageCacheManager._internal();

  // LRU Cache với max 50 items
  final _cache = <String, CachedImage>{};
  static const int _maxCacheSize = 50;
  static const Duration _defaultTtl = Duration(minutes: 30);

  /// Get cached image
  CachedImage? get(String key) {
    final cached = _cache[key];
    if (cached == null) return null;
    
    // Check expiry
    if (cached.isExpired) {
      _cache.remove(key);
      return null;
    }
    
    // Move to end (LRU)
    _cache.remove(key);
    _cache[key] = cached;
    
    return cached;
  }

  /// Cache image bytes
  void put(String key, List<int> bytes, {Duration? ttl}) {
    // Evict oldest if full
    while (_cache.length >= _maxCacheSize) {
      _cache.remove(_cache.keys.first);
    }
    
    _cache[key] = CachedImage(
      bytes: bytes,
      expiresAt: DateTime.now().add(ttl ?? _defaultTtl),
    );
  }

  /// Clear all cache
  void clear() => _cache.clear();

  /// Clear expired entries
  void clearExpired() {
    _cache.removeWhere((_, value) => value.isExpired);
  }

  /// Current cache size
  int get size => _cache.length;
}

class CachedImage {
  final List<int> bytes;
  final DateTime expiresAt;

  CachedImage({required this.bytes, required this.expiresAt});

  bool get isExpired => DateTime.now().isAfter(expiresAt);
}
