#!/bin/bash
# ダブルクリック用の macOS アプリ（.app）をつくる。
# コード署名も Apple Developer 契約も不要。ローカルで動くだけの薄いランチャー。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="ローカル音楽生成"
APP="$PROJECT_ROOT/$APP_NAME.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>$APP_NAME</string>
    <key>CFBundleIdentifier</key><string>local.music.generator</string>
    <key>CFBundleVersion</key><string>0.1.0</string>
    <key>CFBundleShortVersionString</key><string>0.1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSArchitecturePriority</key><array><string>arm64</string></array>
</dict>
</plist>
PLIST

# ターミナルで start.command を開く（進捗と停止操作を見せるため）
cat > "$APP/Contents/MacOS/launcher" <<LAUNCHER
#!/bin/bash
open -a Terminal "$PROJECT_ROOT/start.command"
LAUNCHER

chmod +x "$APP/Contents/MacOS/launcher"

echo "✅ 作成しました: $APP"
echo "   ダブルクリックで起動できます。"
echo "   初回は「開発元が未確認」と出ることがあります。右クリック → 開く を選んでください。"
