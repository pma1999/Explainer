/**
 * generate-icons.cjs
 * Generates PWA PNG icons from SVG source files.
 * Requires: npm install --save-dev @resvg/resvg-js
 * Or falls back to writing placeholder PNGs if not available.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const ICONS_DIR = path.join(__dirname, '../frontend/icons');

// Try to use @resvg/resvg-js if available, otherwise write a placeholder PNG
async function generatePNG(svgPath, outputPath, size) {
  try {
    const { Resvg } = require('@resvg/resvg-js');
    const svgData = fs.readFileSync(svgPath, 'utf8');
    const resvg = new Resvg(svgData, {
      fitTo: { mode: 'width', value: size },
    });
    const pngData = resvg.render();
    const pngBuffer = pngData.asPng();
    fs.writeFileSync(outputPath, pngBuffer);
    console.log(`✓ Generated ${path.basename(outputPath)} (${size}x${size})`);
  } catch (err) {
    if (err.code === 'MODULE_NOT_FOUND') {
      // Fallback: write a minimal valid PNG using raw bytes
      // This is a 1x1 transparent PNG that gets scaled — not ideal but valid
      writeFallbackPNG(outputPath, size);
    } else {
      throw err;
    }
  }
}

/**
 * Write a minimal solid-color PNG for fallback.
 * Uses a pure Node.js implementation — no dependencies.
 * Color: #0d1117 (app background) with a purple hex overlay.
 */
function writeFallbackPNG(outputPath, size) {
  // We'll generate a proper PNG using pure Node.js
  const png = createSimplePNG(size, size, 0x0d, 0x11, 0x17);
  fs.writeFileSync(outputPath, png);
  console.log(`⚠  Generated fallback PNG for ${path.basename(outputPath)} (${size}x${size}) — install @resvg/resvg-js for full quality`);
}

/**
 * Create a solid-color PNG using raw PNG format (no deps).
 * Returns a Buffer containing valid PNG data.
 */
function createSimplePNG(width, height, r, g, b) {
  const zlib = require('zlib');

  // PNG signature
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

  // IHDR chunk
  function ihdr(w, h) {
    const data = Buffer.alloc(13);
    data.writeUInt32BE(w, 0);
    data.writeUInt32BE(h, 4);
    data[8] = 8;  // bit depth
    data[9] = 2;  // color type: RGB
    data[10] = 0; // compression
    data[11] = 0; // filter
    data[12] = 0; // interlace
    return makeChunk('IHDR', data);
  }

  // IDAT chunk — raw pixel data
  function idat(w, h) {
    // Each row: filter byte (0) + RGB pixels
    const rowSize = 1 + w * 3;
    const raw = Buffer.alloc(h * rowSize);
    for (let y = 0; y < h; y++) {
      const rowOffset = y * rowSize;
      raw[rowOffset] = 0; // filter type: None
      for (let x = 0; x < w; x++) {
        const px = rowOffset + 1 + x * 3;
        raw[px] = r;
        raw[px + 1] = g;
        raw[px + 2] = b;
      }
    }
    const compressed = zlib.deflateSync(raw, { level: 9 });
    return makeChunk('IDAT', compressed);
  }

  // IEND chunk
  function iend() {
    return makeChunk('IEND', Buffer.alloc(0));
  }

  function makeChunk(type, data) {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length, 0);
    const typeBuffer = Buffer.from(type, 'ascii');
    const crcBuffer = Buffer.alloc(4);
    const crcData = Buffer.concat([typeBuffer, data]);
    crcBuffer.writeUInt32BE(crc32(crcData), 0);
    return Buffer.concat([len, typeBuffer, data, crcBuffer]);
  }

  function crc32(buf) {
    let crc = 0xffffffff;
    const table = makeCRCTable();
    for (let i = 0; i < buf.length; i++) {
      crc = (crc >>> 8) ^ table[(crc ^ buf[i]) & 0xff];
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function makeCRCTable() {
    const table = [];
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      }
      table[n] = c;
    }
    return table;
  }

  return Buffer.concat([signature, ihdr(width, height), idat(width, height), iend()]);
}

async function main() {
  if (!fs.existsSync(ICONS_DIR)) {
    fs.mkdirSync(ICONS_DIR, { recursive: true });
  }

  const icons = [
    { svg: 'icon-192.svg', png: 'icon-192.png', size: 192 },
    { svg: 'icon-512.svg', png: 'icon-512.png', size: 512 },
    { svg: 'apple-touch-icon.svg', png: 'apple-touch-icon.png', size: 180 },
  ];

  for (const icon of icons) {
    const svgPath = path.join(ICONS_DIR, icon.svg);
    const pngPath = path.join(ICONS_DIR, icon.png);
    if (!fs.existsSync(svgPath)) {
      console.warn(`⚠  SVG not found: ${icon.svg}`);
      continue;
    }
    await generatePNG(svgPath, pngPath, icon.size);
  }
}

main().catch(console.error);
