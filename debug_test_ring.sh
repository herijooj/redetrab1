#!/bin/bash
# Auto-debug script for Ring Network Test

echo "🔗 Starting Ring Network Test in Debug Mode 🔗"
echo "=============================================="

# Kill any existing instances
pkill -f "python test_ring.py" 2>/dev/null

# Start all 4 nodes
echo "Starting Node 3..."
python test_ring.py 3 &
P3_PID=$!

sleep 0.5

echo "Starting Node 2..."
python test_ring.py 2 &
P2_PID=$!

sleep 0.5

echo "Starting Node 1..."
python test_ring.py 1 &
P1_PID=$!

sleep 0.5

echo "Starting Node 0 (Initiator)..."  
python test_ring.py 0 &
P0_PID=$!

echo ""
echo "🌐 Ring network test is running!"
echo "Node 0 will initiate test messages after 5 seconds"
echo "Press Ctrl+C to stop all nodes"
echo ""

# Wait for user interrupt
trap 'echo ""; echo "Stopping all nodes..."; kill $P0_PID $P1_PID $P2_PID $P3_PID 2>/dev/null; exit 0' INT

# Wait for all background processes
wait