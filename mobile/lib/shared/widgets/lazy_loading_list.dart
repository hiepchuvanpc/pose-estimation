import 'package:flutter/material.dart';

/// Lazy loading list widget với pagination
class LazyLoadingList<T> extends StatefulWidget {
  final Future<List<T>> Function(int page, int pageSize) loadPage;
  final Widget Function(BuildContext context, T item, int index) itemBuilder;
  final Widget? loadingWidget;
  final Widget? emptyWidget;
  final Widget? errorWidget;
  final int pageSize;
  final double scrollThreshold;
  final EdgeInsets? padding;
  final ScrollPhysics? physics;

  const LazyLoadingList({
    super.key,
    required this.loadPage,
    required this.itemBuilder,
    this.loadingWidget,
    this.emptyWidget,
    this.errorWidget,
    this.pageSize = 20,
    this.scrollThreshold = 200,
    this.padding,
    this.physics,
  });

  @override
  State<LazyLoadingList<T>> createState() => _LazyLoadingListState<T>();
}

class _LazyLoadingListState<T> extends State<LazyLoadingList<T>> {
  final List<T> _items = [];
  final ScrollController _scrollController = ScrollController();
  
  int _currentPage = 0;
  bool _isLoading = false;
  bool _hasMore = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
    _loadNextPage();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
        _scrollController.position.maxScrollExtent - widget.scrollThreshold) {
      _loadNextPage();
    }
  }

  Future<void> _loadNextPage() async {
    if (_isLoading || !_hasMore) return;

    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final newItems = await widget.loadPage(_currentPage, widget.pageSize);
      
      if (mounted) {
        setState(() {
          _items.addAll(newItems);
          _currentPage++;
          _hasMore = newItems.length >= widget.pageSize;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  Future<void> refresh() async {
    setState(() {
      _items.clear();
      _currentPage = 0;
      _hasMore = true;
      _error = null;
    });
    await _loadNextPage();
  }

  @override
  Widget build(BuildContext context) {
    if (_items.isEmpty && _isLoading) {
      return widget.loadingWidget ?? const Center(
        child: CircularProgressIndicator(),
      );
    }

    if (_items.isEmpty && _error != null) {
      return widget.errorWidget ?? Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.red),
            const SizedBox(height: 16),
            Text('Lỗi: $_error'),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: refresh,
              child: const Text('Thử lại'),
            ),
          ],
        ),
      );
    }

    if (_items.isEmpty) {
      return widget.emptyWidget ?? const Center(
        child: Text('Không có dữ liệu'),
      );
    }

    return RefreshIndicator(
      onRefresh: refresh,
      child: ListView.builder(
        controller: _scrollController,
        padding: widget.padding,
        physics: widget.physics ?? const AlwaysScrollableScrollPhysics(),
        itemCount: _items.length + (_hasMore ? 1 : 0),
        itemBuilder: (context, index) {
          if (index >= _items.length) {
            return const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            );
          }
          return widget.itemBuilder(context, _items[index], index);
        },
      ),
    );
  }
}

/// Lazy loading grid widget với pagination
class LazyLoadingGrid<T> extends StatefulWidget {
  final Future<List<T>> Function(int page, int pageSize) loadPage;
  final Widget Function(BuildContext context, T item, int index) itemBuilder;
  final Widget? loadingWidget;
  final Widget? emptyWidget;
  final Widget? errorWidget;
  final int pageSize;
  final double scrollThreshold;
  final EdgeInsets? padding;
  final int crossAxisCount;
  final double mainAxisSpacing;
  final double crossAxisSpacing;
  final double childAspectRatio;

  const LazyLoadingGrid({
    super.key,
    required this.loadPage,
    required this.itemBuilder,
    this.loadingWidget,
    this.emptyWidget,
    this.errorWidget,
    this.pageSize = 20,
    this.scrollThreshold = 200,
    this.padding,
    this.crossAxisCount = 2,
    this.mainAxisSpacing = 8,
    this.crossAxisSpacing = 8,
    this.childAspectRatio = 1.0,
  });

  @override
  State<LazyLoadingGrid<T>> createState() => _LazyLoadingGridState<T>();
}

class _LazyLoadingGridState<T> extends State<LazyLoadingGrid<T>> {
  final List<T> _items = [];
  final ScrollController _scrollController = ScrollController();
  
  int _currentPage = 0;
  bool _isLoading = false;
  bool _hasMore = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
    _loadNextPage();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
        _scrollController.position.maxScrollExtent - widget.scrollThreshold) {
      _loadNextPage();
    }
  }

  Future<void> _loadNextPage() async {
    if (_isLoading || !_hasMore) return;

    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final newItems = await widget.loadPage(_currentPage, widget.pageSize);
      
      if (mounted) {
        setState(() {
          _items.addAll(newItems);
          _currentPage++;
          _hasMore = newItems.length >= widget.pageSize;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  Future<void> refresh() async {
    setState(() {
      _items.clear();
      _currentPage = 0;
      _hasMore = true;
      _error = null;
    });
    await _loadNextPage();
  }

  @override
  Widget build(BuildContext context) {
    if (_items.isEmpty && _isLoading) {
      return widget.loadingWidget ?? const Center(
        child: CircularProgressIndicator(),
      );
    }

    if (_items.isEmpty && _error != null) {
      return widget.errorWidget ?? Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.red),
            const SizedBox(height: 16),
            Text('Lỗi: $_error'),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: refresh,
              child: const Text('Thử lại'),
            ),
          ],
        ),
      );
    }

    if (_items.isEmpty) {
      return widget.emptyWidget ?? const Center(
        child: Text('Không có dữ liệu'),
      );
    }

    return RefreshIndicator(
      onRefresh: refresh,
      child: CustomScrollView(
        controller: _scrollController,
        slivers: [
          SliverPadding(
            padding: widget.padding ?? EdgeInsets.zero,
            sliver: SliverGrid(
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: widget.crossAxisCount,
                mainAxisSpacing: widget.mainAxisSpacing,
                crossAxisSpacing: widget.crossAxisSpacing,
                childAspectRatio: widget.childAspectRatio,
              ),
              delegate: SliverChildBuilderDelegate(
                (context, index) {
                  return widget.itemBuilder(context, _items[index], index);
                },
                childCount: _items.length,
              ),
            ),
          ),
          if (_hasMore)
            const SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Center(child: CircularProgressIndicator()),
              ),
            ),
        ],
      ),
    );
  }
}
