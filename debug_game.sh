#!/bin/bash
# Auto-debug script for Hearts game

echo "🎴 Starting Hearts Game in Auto-Debug Mode 🎴"
echo "=============================================="

# Kill any existing instances
pkill -f "python launcher.py" 2>/dev/null

# Start all 4 players in auto mode with debug logging
echo "Starting Player 3..."
python launcher.py 3 --auto &
P3_PID=$!

sleep 0.5

echo "Starting Player 2..."
python launcher.py 2 --auto &
P2_PID=$!

sleep 0.5

echo "Starting Player 1..."
python launcher.py 1 --auto &
P1_PID=$!

sleep 0.5

echo "Starting Player 0 (Coordinator)..."
python launcher.py 0 --auto &
P0_PID=$!

echo ""
echo "🎮 Game is running in auto-play mode with debug logging!"
echo "Press Ctrl+C to stop all players"
echo ""

# Wait for user interrupt
trap 'echo ""; echo "Stopping all players..."; kill $P0_PID $P1_PID $P2_PID $P3_PID 2>/dev/null; exit 0' INT

# Wait for all background processes
wait