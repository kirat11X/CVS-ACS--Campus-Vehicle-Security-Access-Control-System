#!/usr/bin/env bash
# Regenerates every app icon and splash screen from the SVG sources (needs ImageMagick 7: `magick`).
#   public/icon.svg            rounded mark: favicon, web manifest, legacy Android launcher icon
#   assets/icon-maskable.svg   full-bleed mark: maskable web icon, apple-touch-icon, round launcher icon
#   assets/icon-foreground.svg adaptive-icon foreground (108 dp canvas, content inside the 72 dp safe zone)
set -euo pipefail
cd "$(dirname "$0")/.."

BG="#0f172a"
render() { magick -background none -density 384 "$1" -resize "$2x$2" "$3"; }

mkdir -p public/icons
render public/icon.svg 192 public/icons/icon-192.png
render public/icon.svg 512 public/icons/icon-512.png
render assets/icon-maskable.svg 512 public/icons/icon-maskable-512.png
magick -background "$BG" -density 384 assets/icon-maskable.svg -resize 180x180 -flatten public/icons/apple-touch-icon.png

RES=android/app/src/main/res
if [ -d "$RES" ]; then
  for spec in mdpi:48:108 hdpi:72:162 xhdpi:96:216 xxhdpi:144:324 xxxhdpi:192:432; do
    IFS=: read -r density size fg <<<"$spec"
    render public/icon.svg "$size" "$RES/mipmap-$density/ic_launcher.png"
    render assets/icon-foreground.svg "$fg" "$RES/mipmap-$density/ic_launcher_foreground.png"
    half=$((size / 2))
    magick -background none -density 384 assets/icon-maskable.svg -resize "${size}x${size}" \
      \( +clone -alpha extract -fill black -colorize 100 -fill white -draw "circle $half,$half $half,0" \) \
      -alpha off -compose CopyOpacity -composite "$RES/mipmap-$density/ic_launcher_round.png"
  done
  # Splash screens keep each template file's size; the mark is 28% of the shorter side.
  find "$RES" -name splash.png | while read -r f; do
    read -r w h < <(magick identify -format "%w %h\n" "$f")
    m=$(( (w < h ? w : h) * 28 / 100 ))
    magick -size "${w}x${h}" "xc:$BG" \( -background none -density 384 public/icon.svg -resize "${m}x${m}" \) -gravity center -composite "$f"
  done
fi
echo "Icons regenerated."
