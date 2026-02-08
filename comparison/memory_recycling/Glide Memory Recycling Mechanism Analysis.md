# Glide Memory Recycling Mechanism Analysis

This document traces the complete lifecycle of a Bitmap in Glide, from creation in `Downsampler` to recycling via `BitmapPool`.

---

## Overview: The Bitmap Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BITMAP LIFECYCLE FLOW                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. CREATION                          2. WRAPPING                            │
│  ┌─────────────────┐                  ┌─────────────────┐                   │
│  │   Downsampler   │ ─── Bitmap ───►  │  BitmapResource │                   │
│  │  (decode)       │                  │    (wrapper)    │                   │
│  └─────────────────┘                  └────────┬────────┘                   │
│         │                                      │                            │
│         │ bitmapPool.getDirty()                │ wrapped in                 │
│         ▼                                      ▼                            │
│  ┌─────────────────┐                  ┌─────────────────┐                   │
│  │  LruBitmapPool  │                  │  EngineResource │                   │
│  │ (reuse bitmaps) │                  │ (ref counting)  │                   │
│  └─────────────────┘                  └────────┬────────┘                   │
│         ▲                                      │                            │
│         │                                      │ stored in                  │
│         │                                      ▼                            │
│         │                             ┌─────────────────┐                   │
│         │                             │ ActiveResources │                   │
│         │                             │  (in-use cache) │                   │
│         │                             └────────┬────────┘                   │
│         │                                      │                            │
│  3. RECYCLING                         4. LIFECYCLE                          │
│  ┌─────────────────┐                  ┌─────────────────┐                   │
│  │ BitmapResource  │ ◄── release ──── │  SingleRequest  │                   │
│  │   .recycle()    │                  │    .clear()     │                   │
│  └────────┬────────┘                  └─────────────────┘                   │
│           │                                                                  │
│           │ bitmapPool.put(bitmap)                                          │
│           ▼                                                                  │
│  ┌─────────────────┐                                                        │
│  │  LruBitmapPool  │  ─── CYCLE COMPLETE ───                                │
│  │   (storage)     │                                                        │
│  └─────────────────┘                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Bitmap Creation in Downsampler

### Location
**File:** `library/src/main/java/com/bumptech/glide/load/resource/bitmap/Downsampler.java`

### Key Method: `decode()`
**Lines 188-216**

```java
@SuppressWarnings({"resource", "deprecation"})
public Resource<Bitmap> decode(InputStream is, int requestedWidth, int requestedHeight,
    Options options, DecodeCallbacks callbacks) throws IOException {
  // ... setup code ...
  
  try {
    Bitmap result = decodeFromWrappedStreams(is, bitmapFactoryOptions,
        downsampleStrategy, decodeFormat, isHardwareConfigAllowed, requestedWidth,
        requestedHeight, fixBitmapToRequestedDimensions, callbacks);
    
    // KEY: Bitmap is wrapped in BitmapResource with bitmapPool reference
    return BitmapResource.obtain(result, bitmapPool);
  } finally {
    releaseOptions(bitmapFactoryOptions);
    byteArrayPool.put(bytesForOptions);
  }
}
```

### Bitmap Pool Integration During Decode
**Lines 297-301 in `decodeFromWrappedStreams()`**

```java
// If this isn't an image, or BitmapFactory was unable to parse the size, width and height
// will be -1 here.
if (expectedWidth > 0 && expectedHeight > 0) {
  setInBitmap(options, bitmapPool, expectedWidth, expectedHeight);
}
Bitmap downsampled = decodeStream(is, options, callbacks, bitmapPool);
```

### `setInBitmap()` - Bitmap Reuse from Pool
**Lines 667-690**

```java
@TargetApi(Build.VERSION_CODES.O)
private static void setInBitmap(
    BitmapFactory.Options options, BitmapPool bitmapPool, int width, int height) {
  // ... config checks ...
  
  // KEY: Gets a dirty (potentially uncleared) bitmap from pool for reuse
  options.inBitmap = bitmapPool.getDirty(width, height, expectedConfig);
}
```

### Rotation Handling - Intermediate Bitmap Recycling
**Lines 309-319**

```java
Bitmap rotated = null;
if (downsampled != null) {
  downsampled.setDensity(displayMetrics.densityDpi);

  rotated = TransformationUtils.rotateImageExif(bitmapPool, downsampled, orientation);
  if (!downsampled.equals(rotated)) {
    // KEY: If rotation created a new bitmap, return the original to the pool
    bitmapPool.put(downsampled);
  }
}
```

---

## 2. BitmapResource - The Resource Wrapper

### Location
**File:** `library/src/main/java/com/bumptech/glide/load/resource/bitmap/BitmapResource.java`

### Complete Class (68 lines)

```java
public class BitmapResource implements Resource<Bitmap>, Initializable {
  private final Bitmap bitmap;
  private final BitmapPool bitmapPool;

  /**
   * Factory method to obtain a BitmapResource
   */
  @Nullable
  public static BitmapResource obtain(@Nullable Bitmap bitmap, @NonNull BitmapPool bitmapPool) {
    if (bitmap == null) {
      return null;
    } else {
      return new BitmapResource(bitmap, bitmapPool);
    }
  }

  public BitmapResource(@NonNull Bitmap bitmap, @NonNull BitmapPool bitmapPool) {
    this.bitmap = Preconditions.checkNotNull(bitmap, "Bitmap must not be null");
    this.bitmapPool = Preconditions.checkNotNull(bitmapPool, "BitmapPool must not be null");
  }

  @NonNull
  @Override
  public Bitmap get() {
    return bitmap;
  }

  @Override
  public int getSize() {
    return Util.getBitmapByteSize(bitmap);
  }

  /**
   * ⭐ KEY METHOD: Returns the bitmap to the pool for reuse
   */
  @Override
  public void recycle() {
    bitmapPool.put(bitmap);
  }

  @Override
  public void initialize() {
    bitmap.prepareToDraw();
  }
}
```

### ⭐ The Critical `recycle()` Method

```java
@Override
public void recycle() {
  bitmapPool.put(bitmap);
}
```

**This is the specific `Resource.recycle()` implementation responsible for returning Bitmaps to the pool.**

---

## 3. EngineResource - Reference Counting Wrapper

### Location
**File:** `library/src/main/java/com/bumptech/glide/load/engine/EngineResource.java`

### Purpose
`EngineResource` wraps `BitmapResource` (or any `Resource`) to add reference counting for safe memory management.

### Key Fields
```java
class EngineResource<Z> implements Resource<Z> {
  private final boolean isCacheable;
  private final boolean isRecyclable;
  private ResourceListener listener;
  private Key key;
  private int acquired;       // Reference count
  private boolean isRecycled;
  private final Resource<Z> resource;  // The wrapped BitmapResource
```

### Reference Counting: `acquire()` and `release()`

```java
/**
 * Increments the number of consumers using the wrapped resource.
 */
void acquire() {
  if (isRecycled) {
    throw new IllegalStateException("Cannot acquire a recycled resource");
  }
  if (!Looper.getMainLooper().equals(Looper.myLooper())) {
    throw new IllegalThreadStateException("Must call acquire on the main thread");
  }
  ++acquired;
}

/**
 * Decrements the number of consumers using the wrapped resource.
 */
void release() {
  if (acquired <= 0) {
    throw new IllegalStateException("Cannot release a recycled or not yet acquired resource");
  }
  if (!Looper.getMainLooper().equals(Looper.myLooper())) {
    throw new IllegalThreadStateException("Must call release on the main thread");
  }
  if (--acquired == 0) {
    // KEY: When no more consumers, notify the listener (Engine)
    listener.onResourceReleased(key, this);
  }
}
```

### EngineResource.recycle() - Delegates to Wrapped Resource

```java
@Override
public void recycle() {
  if (acquired > 0) {
    throw new IllegalStateException("Cannot recycle a resource while it is still acquired");
  }
  if (isRecycled) {
    throw new IllegalStateException("Cannot recycle a resource that has already been recycled");
  }
  isRecycled = true;
  if (isRecyclable) {
    resource.recycle();  // Calls BitmapResource.recycle() → bitmapPool.put()
  }
}
```

---

## 4. Engine - The Coordinator

### Location
**File:** `library/src/main/java/com/bumptech/glide/load/engine/Engine.java`

### Engine Implements `EngineResource.ResourceListener`

```java
public class Engine implements EngineJobListener,
    MemoryCache.ResourceRemovedListener,
    EngineResource.ResourceListener {
```

### Release Flow Entry Point

```java
public void release(Resource<?> resource) {
  Util.assertMainThread();
  if (resource instanceof EngineResource) {
    ((EngineResource<?>) resource).release();
  } else {
    throw new IllegalArgumentException("Cannot release anything but an EngineResource");
  }
}
```

### `onResourceReleased()` - Called When Reference Count Hits Zero

**Lines 321-330**

```java
@Override
public void onResourceReleased(Key cacheKey, EngineResource<?> resource) {
  Util.assertMainThread();
  activeResources.deactivate(cacheKey);  // Remove from active resources
  if (resource.isCacheable()) {
    cache.put(cacheKey, resource);  // Move to LRU memory cache
  } else {
    resourceRecycler.recycle(resource);  // Recycle immediately
  }
}
```

### `onResourceRemoved()` - Called When Evicted from Cache

**Lines 315-319**

```java
@Override
public void onResourceRemoved(@NonNull final Resource<?> resource) {
  Util.assertMainThread();
  resourceRecycler.recycle(resource);  // Trigger recycling
}
```

---

## 5. ResourceRecycler - Safe Recycling

### Location
**File:** `library/src/main/java/com/bumptech/glide/load/engine/ResourceRecycler.java`

### Complete Class

```java
class ResourceRecycler {
  private boolean isRecycling;
  private final Handler handler =
      new Handler(Looper.getMainLooper(), new ResourceRecyclerCallback());

  void recycle(Resource<?> resource) {
    Util.assertMainThread();

    if (isRecycling) {
      // If a resource has sub-resources, releasing a sub resource can cause it's parent
      // to be synchronously evicted which leads to a recycle loop. Posting breaks this loop.
      handler.obtainMessage(ResourceRecyclerCallback.RECYCLE_RESOURCE, resource).sendToTarget();
    } else {
      isRecycling = true;
      resource.recycle();  // → EngineResource.recycle() → BitmapResource.recycle()
      isRecycling = false;
    }
  }

  private static final class ResourceRecyclerCallback implements Handler.Callback {
    static final int RECYCLE_RESOURCE = 1;

    @Override
    public boolean handleMessage(Message message) {
      if (message.what == RECYCLE_RESOURCE) {
        Resource<?> resource = (Resource<?>) message.obj;
        resource.recycle();
        return true;
      }
      return false;
    }
  }
}
```

---

## 6. LruBitmapPool - The Pool Implementation

### Location
**File:** `library/src/main/java/com/bumptech/glide/load/engine/bitmap_recycle/LruBitmapPool.java`

### `put()` - Storing Bitmaps

**Lines 82-115**

```java
@Override
public synchronized void put(Bitmap bitmap) {
  if (bitmap == null) {
    throw new NullPointerException("Bitmap must not be null");
  }
  if (bitmap.isRecycled()) {
    throw new IllegalStateException("Cannot pool recycled bitmap");
  }
  if (!bitmap.isMutable() || strategy.getSize(bitmap) > maxSize
      || !allowedConfigs.contains(bitmap.getConfig())) {
    // Reject bitmaps that can't be reused
    bitmap.recycle();  // Native recycle (permanent destruction)
    return;
  }

  final int size = strategy.getSize(bitmap);
  strategy.put(bitmap);  // Add to pool strategy (SizeConfigStrategy or AttributeStrategy)
  tracker.add(bitmap);

  puts++;
  currentSize += size;

  evict();  // Evict if over max size
}
```

### `getDirty()` - Retrieving Bitmaps for Reuse

**Lines 137-145**

```java
@NonNull
@Override
public Bitmap getDirty(int width, int height, Bitmap.Config config) {
  Bitmap result = getDirtyOrNull(width, height, config);
  if (result == null) {
    result = createBitmap(width, height, config);  // Falls back to new creation
  }
  return result;
}
```

---

## 7. Lifecycle Trigger: SingleRequest.clear()

### Location
**File:** `library/src/main/java/com/bumptech/glide/request/SingleRequest.java`

### `clear()` - Entry Point for Resource Release

**Lines 305-331**

```java
@Override
public void clear() {
  Util.assertMainThread();
  assertNotCallingCallbacks();
  stateVerifier.throwIfRecycled();
  if (status == Status.CLEARED) {
    return;
  }
  cancel();
  // Resource must be released before canNotifyStatusChanged is called.
  if (resource != null) {
    releaseResource(resource);  // Triggers the release chain
  }
  if (canNotifyCleared()) {
    target.onLoadCleared(getPlaceholderDrawable());
  }
  status = Status.CLEARED;
}

private void releaseResource(Resource<?> resource) {
  engine.release(resource);  // → Engine.release() → EngineResource.release()
  this.resource = null;
}
```

---

## Complete Call Chain Summary

```
1. LIFECYCLE DESTRUCTION
   Fragment/Activity onDestroy → RequestManager → RequestTracker.clearRequests()

2. REQUEST CLEARING  
   → SingleRequest.clear()
   → SingleRequest.releaseResource(resource)
   → Engine.release(resource)

3. REFERENCE COUNT DECREMENT
   → EngineResource.release()
   → if (--acquired == 0): listener.onResourceReleased(key, this)

4. ENGINE HANDLING
   → Engine.onResourceReleased(key, resource)
   → activeResources.deactivate(key)
   → if cacheable: cache.put(key, resource)
   → if not cacheable OR cache eviction: resourceRecycler.recycle(resource)

5. SAFE RECYCLING
   → ResourceRecycler.recycle(resource)
   → EngineResource.recycle()
   → if isRecyclable: resource.recycle()

6. ⭐ BITMAP POOL RETURN
   → BitmapResource.recycle()      ← THE KEY METHOD
   → bitmapPool.put(bitmap)

7. POOL STORAGE
   → LruBitmapPool.put(bitmap)
   → strategy.put(bitmap)
   → Bitmap stored for future reuse via getDirty()
```

---

## Answer to the Question

### Which specific implementation of `Resource.recycle()` is responsible for interacting with the pool?

**`BitmapResource.recycle()`** is the specific implementation that directly interacts with the `BitmapPool`:

```java
// BitmapResource.java, lines 58-61
@Override
public void recycle() {
  bitmapPool.put(bitmap);
}
```

This method:
1. Is called when the `EngineResource` wrapper determines the resource should be recycled
2. Receives a reference to the `BitmapPool` during construction (passed from `Downsampler`)
3. Simply calls `bitmapPool.put(bitmap)` to return the bitmap to the pool
4. Does NOT call `bitmap.recycle()` (native destruction) - that's the pool's decision

The `BitmapPool` (implemented by `LruBitmapPool`) then decides whether to:
- Store the bitmap for later reuse (if it fits pool constraints)
- Call `bitmap.recycle()` (native destruction) if the bitmap can't be pooled
