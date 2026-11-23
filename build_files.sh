#!/bin/bash
echo "Installing Python dependencies..."
python3 -m pip install -r requirements.txt

echo "Collecting static files for WhiteNoise..."
python3 manage.py collectstatic --noinput --clear

echo "Vercel build finished successfully!"
