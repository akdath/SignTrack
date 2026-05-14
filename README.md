# SignTrack – AI Hand Gesture Desktop Controller

SignTrack is an AI-powered desktop automation application that allows users to control their computer using real-time hand gestures through a webcam. It provides a touchless interaction experience using computer vision and machine learning.

## Features

* Cursor movement using hand tracking
* Left click gesture
* Right click gesture
* Scroll up / down using gestures
* Tab switching using thumbs up gesture
* Close active window using thumbs down gesture
* Live webcam preview
* Free and Pro user access system
* Login system with usage timer
* Modern desktop UI built with CustomTkinter

## Technologies Used

* Python
* Flask
* Flask-SQLAlchemy
* SQLite
* HTML5
* CSS3
* JavaScript
* OpenCV
* MediaPipe
* TensorFlow
* Keras
* CustomTkinter
* NumPy
* PyAutoGUI
* Keyboard
* Multithreading

## Gesture Controls

| Gesture         | Action       |
| --------------- | ------------ |
| 👊 Fist         | Left Click   |
| 🖐 Five Fingers | Right Click  |
| ☝ One Finger    | Move Cursor  |
| ✌ Two Fingers   | Scroll       |
| 👍 Thumbs Up    | Switch Tabs  |
| 👎 Thumbs Down  | Close Window |

## Installation

1. Clone the repository:

```bash
git clone https://github.com/akdath/SignTrack.git
cd SignTrack
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the application:

```bash
python main.py
```

## Project Structure

* `main.py` – Main desktop application
* `ceptron.h5` – Trained gesture recognition model
* `users.db` – User database
* `templates/` – Web interface templates
* `static/` – CSS / assets

## Future Improvements

* More gesture commands
* Cross-platform support
* Better gesture accuracy
* Voice control integration
* Cloud sync

## Author

Akshay Dath

## License

This project is for educational and portfolio purposes.
