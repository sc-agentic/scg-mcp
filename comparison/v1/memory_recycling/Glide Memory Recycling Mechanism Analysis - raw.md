# Glide Memory Recycling Mechanism Analysis

## Overview

Glide implements a sophisticated **Bitmap pooling and recycling mechanism** to minimize memory allocations and reduce GC pressure when loading images. This document traces the complete lifecycle of a Bitmap from creation to recycling.

---

## 1. Bitmap Creation in Downsampler

### Entry Point: `Downsampler.decode()`

**File:** `library/src/main/java/com/bumptech/glide/load/resource/bitmap/Downsampler.java`

```java
// Lines 189-216
public Resource<Bitmap> decode(InputStream is, int requestedWidth, int requestedHeight,
    Options options, DecodeCallbacks callbacks) throws IOException {
  // ... setup code ...
  
  try {
    Bitmap result = decodeFromWrappedStreams(is, bitmapFactoryOptions,
        downsampleStrategy, decodeFormat, isHardwareConfigAllowed, requestedWidth,
        requestedHeight, fixBitmapToRequestedDimensions, callbacks);
    
    // ⭐ KEY: Wraps the Bitmap in a BitmapResource with reference to BitmapPool
    return BitmapResource.obtain(result, bitmapPool);
  } finally {
    releaseOptions(bitmapFactoryOptions);
    byteArrayPool.put(bytesForOptions);
  }
}
```

### Bitmap Reuse via `inBitmap` (Pool Integration)

**Lines 667-690:** Before decoding, Glide attempts to reuse a Bitmap from the pool:

```java
private static void setInBitmap(
    BitmapFactory.Options options, BitmapPool bitmapPool, int width, int height) {
  // ... config determination ...
  
  // ⭐ Gets a reusable Bitmap from the pool to decode into
  options.inBitmap = bitmapPool.getDirty(width, height, expectedConfig);
}
```

### Actual Bitmap Decoding

**Lines 566-614:** `decodeStream()` calls `BitmapFactory.decodeStream()`:

```java
private static Bitmap decodeStream(InputStream is, BitmapFactory.Options options,
    DecodeCallbacks callbacks, BitmapPool bitmapPool) throws IOException {
  // ...
  TransformationUtils.getBitmapDrawableLock().lock();
  try {
    result = BitmapFactory.decodeStream(is, null, options);
  } catch (IllegalArgumentException e) {
    // If inBitmap fails, return it to pool and retry without reuse
    if (options.inBitmap != null) {
      bitmapPool.put(options.inBitmap);  // ⭐ Return failed inBitmap to pool
      options.inBitmap = null;
      return decodeStream(is, options, callbacks, bitmapPool);
    }
    throw bitmapAssertionException;
  } finally {
    TransformationUtils.getBitmapDrawableLock().unlock();
  }
  return result;
}
```

---

## 2. BitmapResource - The Resource Wrapper

**File:** `library/src/main/java/com/bumptech/glide/load/resource/bitmap/BitmapResource.java`

### Structure

```java
public class BitmapResource implements Resource<Bitmap>, Initializable {
  private final Bitmap bitmap;
  private final BitmapPool bitmapPool;

  public BitmapResource(@NonNull Bitmap bitmap, @NonNull BitmapPool bitmapPool) {
    this.bitmap = Preconditions.checkNotNull(bitmap, "Bitmap must not be null");
    this.bitmapPool = Preconditions.checkNotNull(bitmapPool, "BitmapPool must not be null");
  }
```

### ⭐ THE KEY: `recycle()` Method (Lines 58-61)

**This is the specific `Resource.recycle()` implementation responsible for interacting with the pool:**

```java
@Override
public void recycle() {
  bitmapPool.put(bitmap);  // ⭐ Returns Bitmap to pool, NOT Bitmap.recycle()!
}
```

This is the **critical method** you asked about. `BitmapResource.recycle()` does **not** call `Bitmap.recycle()` directly. Instead, it puts the Bitmap back into the `BitmapPool` for reuse.

---

## 3. Resource Interface Contract

**File:** `library/src/main/java/com/bumptech/glide/load/engine/Resource.java`

```java
public interface Resource<Z> {
  /**
   * Cleans up and recycles internal resources.
   * 
   * It is only safe to call this method if there are no current resource consumers 
   * and if this method has not yet been called. Typically this occurs at one of two times:
   * <ul>
   *   <li>During a resource load when the resource is transformed or transcoded before 
   *       any consumers have ever had access to this resource</li>
   *   <li>After all consumers have released this resource and it has been evicted 
   *       from the cache</li>
   * </ul>
   */
  void recycle();
}
```

---

## 4. BitmapPool Implementation

**File:** `library/src/main/java/com/bumptech/glide/load/engine/bitmap_recycle/LruBitmapPool.java`

### `put()` - Adding Bitmaps to the Pool (Lines 82-115)

```java
@Override
public synchronized void put(Bitmap bitmap) {
  if (bitmap == null) {
    throw new NullPointerException("Bitmap must not be null");
  }
  if (bitmap.isRecycled()) {
    throw new IllegalStateException("Cannot pool recycled bitmap");
  }
  
  // Reject if not mutable, too large, or wrong config
  if (!bitmap.isMutable() || strategy.getSize(bitmap) > maxSize
      || !allowedConfigs.contains(bitmap.getConfig())) {
    bitmap.recycle();  // ⭐ Actually recycle if can't pool
    return;
  }

  final int size = strategy.getSize(bitmap);
  strategy.put(bitmap);  // ⭐ Add to LRU strategy
  tracker.add(bitmap);
  
  puts++;
  currentSize += size;
  
  evict();  // Evict if over size limit
}
```

### `getDirty()` - Getting Bitmaps from the Pool (Lines 139-145)

```java
@NonNull
@Override
public Bitmap getDirty(int width, int height, Bitmap.Config config) {
  Bitmap result = getDirtyOrNull(width, height, config);
  if (result == null) {
    result = createBitmap(width, height, config);  // Create new if pool empty
  }
  return result;
}
```

### Eviction with Actual Recycling (Lines 227-247)

```java
private synchronized void trimToSize(long size) {
  while (currentSize > size) {
    final Bitmap removed = strategy.removeLast();
    if (removed == null) {
      currentSize = 0;
      return;
    }
    tracker.remove(removed);
    currentSize -= strategy.getSize(removed);
    evictions++;
    
    removed.recycle();  // ⭐ ONLY here is Bitmap.recycle() called!
  }
}
```

---

## 5. Lifecycle Destruction → Resource Recycling

### Step 1: EngineResource Reference Counting

**File:** `library/src/main/java/com/bumptech/glide/load/engine/EngineResource.java`

```java
class EngineResource<Z> implements Resource<Z> {
  private int acquired;
  private final Resource<Z> resource;  // Wraps BitmapResource
  
  void release() {
    if (--acquired == 0) {
      // ⭐ When no more references, notify listener
      listener.onResourceReleased(key, this);
    }
  }
  
  @Override
  public void recycle() {
    if (isRecyclable) {
      resource.recycle();  // ⭐ Delegates to wrapped Resource (BitmapResource)
    }
  }
}
```

### Step 2: Engine Handles Release

**File:** `library/src/main/java/com/bumptech/glide/load/engine/Engine.java`

```java
@Override
public void onResourceReleased(Key cacheKey, EngineResource<?> resource) {
  Util.assertMainThread();
  activeResources.deactivate(cacheKey);  // Remove from active resources
  
  if (resource.isCacheable()) {
    cache.put(cacheKey, resource);  // Move to memory cache
  } else {
    resourceRecycler.recycle(resource);  // ⭐ Recycle immediately
  }
}

@Override
public void onResourceRemoved(@NonNull final Resource<?> resource) {
  Util.assertMainThread();
  resourceRecycler.recycle(resource);  // ⭐ Called when evicted from cache
}
```

### Step 3: ResourceRecycler

**File:** `library/src/main/java/com/bumptech/glide/load/engine/ResourceRecycler.java`

```java
class ResourceRecycler {
  void recycle(Resource<?> resource) {
    Util.assertMainThread();
    
    if (isRecycling) {
      // Post to handler to break recursion loops
      handler.obtainMessage(ResourceRecyclerCallback.RECYCLE_RESOURCE, resource).sendToTarget();
    } else {
      isRecycling = true;
      resource.recycle();  // ⭐ Calls BitmapResource.recycle() → BitmapPool.put()
      isRecycling = false;
    }
  }
}
```

---

## Complete Lifecycle Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        BITMAP CREATION PHASE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Downsampler.decode()                                                        │
│       │                                                                      │
│       ├──► setInBitmap() ──► BitmapPool.getDirty() ─┐                       │
│       │                                              │                       │
│       ▼                                              ▼                       │
│  BitmapFactory.decodeStream(options.inBitmap)    (reuse pooled Bitmap)      │
│       │                                                                      │
│       ▼                                                                      │
│  BitmapResource.obtain(bitmap, bitmapPool)                                  │
│       │                                                                      │
│       ▼                                                                      │
│  EngineResource wraps BitmapResource                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          USAGE PHASE                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ActiveResources (uses WeakReference) ──► Engine.load()                     │
│       │                                       │                              │
│       │  acquire()                            │ returns Resource             │
│       ▼                                       ▼                              │
│  EngineResource.acquired++               ImageView displays Bitmap          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ View destroyed / Request cleared
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        RELEASE PHASE                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  EngineResource.release()                                                    │
│       │                                                                      │
│       ├──► acquired-- == 0                                                   │
│       │                                                                      │
│       ▼                                                                      │
│  listener.onResourceReleased(key, this)                                     │
│       │                                                                      │
│       ▼                                                                      │
│  Engine.onResourceReleased()                                                │
│       │                                                                      │
│       ├──► activeResources.deactivate(key)                                  │
│       │                                                                      │
│       ├──► if (cacheable) → MemoryCache.put()                               │
│       │                                                                      │
│       └──► if (!cacheable) → ResourceRecycler.recycle()                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Cache eviction or non-cacheable
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        RECYCLING PHASE                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  MemoryCache evicts resource (LRU)                                          │
│       │                                                                      │
│       ▼                                                                      │
│  Engine.onResourceRemoved(resource)                                         │
│       │                                                                      │
│       ▼                                                                      │
│  ResourceRecycler.recycle(resource)                                         │
│       │                                                                      │
│       ▼                                                                      │
│  EngineResource.recycle()                                                   │
│       │                                                                      │
│       ▼                                                                      │
│  ⭐ BitmapResource.recycle()  ←── THE KEY IMPLEMENTATION                    │
│       │                                                                      │
│       ▼                                                                      │
│  BitmapPool.put(bitmap)                                                     │
│       │                                                                      │
│       ├──► if (valid for pooling) → LruPoolStrategy.put(bitmap)             │
│       │                                                                      │
│       └──► if (can't pool) → Bitmap.recycle()  (native memory freed)        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Summary: Key Answer

### Which specific implementation of `Resource.recycle()` is responsible for interacting with the pool?

**Answer:** `BitmapResource.recycle()` is the specific implementation.

**Location:** `library/src/main/java/com/bumptech/glide/load/resource/bitmap/BitmapResource.java`, lines 58-61

```java
@Override
public void recycle() {
  bitmapPool.put(bitmap);
}
```

This single line is the critical bridge between Glide's resource management and the Bitmap pooling system. It:
1. Does **NOT** call `Bitmap.recycle()` directly
2. Returns the Bitmap to `LruBitmapPool` for potential reuse
3. The pool decides whether to keep the Bitmap or call `Bitmap.recycle()` based on pool constraints

### The Complete Chain

```
Lifecycle Event (e.g., Activity destroyed)
    → RequestManager.onDestroy()
        → Request.clear()
            → Engine.release(Resource)
                → EngineResource.release()
                    → Engine.onResourceReleased() (if acquired == 0)
                        → MemoryCache.put() or ResourceRecycler.recycle()
                            → EngineResource.recycle()
                                → BitmapResource.recycle()  ⭐ THE KEY
                                    → LruBitmapPool.put(bitmap)
```
