#!/bin/bash

set -e

echo "Pepper vigiclient installation script"

VIGICLIENT_DIR="/data/vigiclient"

if [ -d "$VIGICLIENT_DIR" ]; then
    echo "Warning: $VIGICLIENT_DIR already exists"
    read -p "Do you want to overwrite? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled"
        exit 1
    fi
    rm -rf "$VIGICLIENT_DIR"
fi

echo "Creating $VIGICLIENT_DIR..."
mkdir -p "$VIGICLIENT_DIR"

echo "Copying vigiclient files..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR"/*.js "$SCRIPT_DIR"/*.json "$VIGICLIENT_DIR/"

echo "Installing Node.js dependencies..."
cd "$VIGICLIENT_DIR"
npm install --production

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "1. Edit $VIGICLIENT_DIR/robot.json with your vigibot.com credentials"
echo "2. Start the client: node $VIGICLIENT_DIR/clientrobotpi.js"
echo ""
