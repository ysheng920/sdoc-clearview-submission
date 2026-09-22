/**
 * Utility to detect and auto-crop excessive white/blank margins from scanned PDF pages.
 * Scans often place a small form/receipt in the corner of a large A4 canvas (e.g. 1240x1754).
 * By trimming the blank borders, the actual document text expands to fill the screen (2-3x larger).
 */

interface CropResult {
  croppedSrc: string
  hasCrop: boolean
}

const cropCache = new Map<string, Promise<CropResult>>()

export function autoCropScannedImage(src: string, padding = 24): Promise<CropResult> {
  if (!src) return Promise.resolve({ croppedSrc: src, hasCrop: false })

  const cached = cropCache.get(src)
  if (cached) return cached

  const promise = new Promise<CropResult>((resolve) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'

    img.onload = () => {
      const { naturalWidth: w, naturalHeight: h } = img
      if (!w || !h || w < 80 || h < 80) {
        resolve({ croppedSrc: src, hasCrop: false })
        return
      }

      try {
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvas.getContext('2d', { willReadFrequently: true })
        if (!ctx) {
          resolve({ croppedSrc: src, hasCrop: false })
          return
        }

        ctx.drawImage(img, 0, 0)
        const imgData = ctx.getImageData(0, 0, w, h)
        const data = imgData.data

        let minX = w
        let minY = h
        let maxX = 0
        let maxY = 0
        let nonWhitePixels = 0

        // Step by 2 for sub-10ms performance on 1-2MP scans
        for (let y = 0; y < h; y += 2) {
          for (let x = 0; x < w; x += 2) {
            const idx = (y * w + x) * 4
            const r = data[idx]
            const g = data[idx + 1]
            const b = data[idx + 2]
            const a = data[idx + 3]

            // Consider non-white if pixel is opaque and darker than near-white (#f2f2f2)
            if (a > 30 && (r < 242 || g < 242 || b < 242)) {
              nonWhitePixels++
              if (x < minX) minX = x
              if (x > maxX) maxX = x
              if (y < minY) minY = y
              if (y > maxY) maxY = y
            }
          }
        }

        const contentW = maxX - minX
        const contentH = maxY - minY

        // If not enough content or content already covers > 82% of width and height, no need to crop
        if (nonWhitePixels < 60 || (contentW > w * 0.82 && contentH > h * 0.82)) {
          resolve({ croppedSrc: src, hasCrop: false })
          return
        }

        const cropX = Math.max(0, minX - padding)
        const cropY = Math.max(0, minY - padding)
        const cropW = Math.min(w - cropX, contentW + padding * 2)
        const cropH = Math.min(h - cropY, contentH + padding * 2)

        const cropCanvas = document.createElement('canvas')
        cropCanvas.width = cropW
        cropCanvas.height = cropH
        const cropCtx = cropCanvas.getContext('2d')
        if (!cropCtx) {
          resolve({ croppedSrc: src, hasCrop: false })
          return
        }

        cropCtx.drawImage(canvas, cropX, cropY, cropW, cropH, 0, 0, cropW, cropH)
        resolve({ croppedSrc: cropCanvas.toDataURL('image/png'), hasCrop: true })
      } catch {
        resolve({ croppedSrc: src, hasCrop: false })
      }
    }

    img.onerror = () => {
      resolve({ croppedSrc: src, hasCrop: false })
    }

    img.src = src
  })

  cropCache.set(src, promise)
  return promise
}
