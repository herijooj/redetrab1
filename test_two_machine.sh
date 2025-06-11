#!/bin/bash
# Two-machine ring network test launcher

echo "🔗 Two-Machine Ring Network Test Launcher 🔗"
echo "============================================="
echo
echo "This script helps you test the ring network between two machines."
echo
echo "IMPORTANT: Update the IP addresses in test_two_machine_ring.py first!"
echo "  - MACHINE_1_IP = \"192.168.100.9\"   # Your machine 1 IP"
echo "  - MACHINE_2_IP = \"192.168.100.18\"  # Your machine 2 IP"
echo

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <machine_number>"
    echo
    echo "  machine_number: 1 or 2"
    echo
    echo "Examples:"
    echo "  $0 1    # Run on machine 1 (initiates test)"
    echo "  $0 2    # Run on machine 2 (responds to test)"
    echo
    echo "Instructions:"
    echo "  1. Start machine 2 first: ./test_two_machine.sh 2"
    echo "  2. Then start machine 1: ./test_two_machine.sh 1"
    echo "  3. Watch for 'RING CONNECTIVITY VERIFIED' messages"
    echo
    exit 1
fi

MACHINE_NUM=$1

if [ "$MACHINE_NUM" != "1" ] && [ "$MACHINE_NUM" != "2" ]; then
    echo "Error: Machine number must be 1 or 2"
    exit 1
fi

echo "Starting test for Machine $MACHINE_NUM..."
echo "Press Ctrl+C to stop the test"
echo

# Kill any existing instances
pkill -f "python test_two_machine_ring.py" 2>/dev/null

# Start the test
python3 test_two_machine_ring.py $MACHINE_NUM