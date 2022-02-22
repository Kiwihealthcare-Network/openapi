#!/bin/bash

echo "`python3 -V`"
python3 -m venv venv
if [ ! -f "activate" ]; then
	ln -s venv/bin/activate .
fi
echo "Install Successfully"
echo "** Please run '. ./activate' to enter the venv **"