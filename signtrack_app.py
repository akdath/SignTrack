import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import threading
import cv2
import numpy as np
import pyautogui
import time
import keyboard
import os
import ctypes
import ctypes.wintypes
import mediapipe as mp
from tensorflow.keras.models import load_model
import sqlite3
from datetime import datetime, timedelta

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
pyautogui.FAILSAFE=False

IMG_SIZE=64
CLASS_NAMES=['thumbs_down', 'fist', 'one_finger', 'five_fingers', 'thumbs_up', 'two_fingers']
GESTURE_THRESHOLDS={
    'thumbs_down':0.9,
    'fist':0.4,
    'one_finger':0.7,
    'five_fingers':0.7,
    'thumbs_up':0.5,
    'two_fingers':0.7
}
CORNER_MAPPING={"Top Left":(0,0), "Top Right":(1,0), "Bottom Left":(0,1), "Bottom Right":(1,1)}

last_gesture_times={
    'fist':0,
    'five_fingers':0,
    'one_finger':0,
    'two_fingers':0,
    'thumbs_up':0,
    'thumbs_down':0
}
cooldown_times={
    'fist':1,
    'five_fingers':1,
    'one_finger':0.02,
    'two_fingers':0.15,
    'thumbs_up':2,
    'thumbs_down':1.0
}
thumbs_up_held=False
thumbs_up_position=0
thumbs_down_last_time=0
scrolling_up=False
scrolling_down=False

last_tab_switch_time=0
tab_switch_cooldown=0.8
THUMBS_UP_HORIZONTAL_THRESHOLD_PIXELS=5
last_cursor_x=0
last_cursor_y=0
cursor_smoothing=0.2

mp_hands=mp.solutions.hands
hands=mp_hands.Hands(static_image_mode=False, max_num_hands=1, min_detection_confidence=0.7)
model_path=os.path.join(os.path.dirname(__file__), 'ceptron.h5')
model=load_model(model_path)

class SignTrackApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.geometry("480x400")
        self.overrideredirect(True)
        self.title("SignTrack")
        self.bind("<Map>", self.on_restore)
        self.time_remaining=7200
        self.timer_running=False
        self.timer_label=None
        self.preview_corner=tk.StringVar(value="Top Right")
        self.preview_size=tk.DoubleVar(value=240)
        self.show_preview=tk.BooleanVar(value=True)
        self.signtrack_enabled=tk.BooleanVar(value=False)
        self.is_pro=False
        self.fg_color="#FFFFFF"
        self.latest_landmarks=None
        self.img_shape=None
        self.stop_thread=threading.Event()
        self.gesture_thread=None
        self.preview_initialized=False
        self.set_position_bottom_right()
        self.create_top_bar()
        self.show_login()
        self.time_remaining=0
        self.timer_label=None
        self.conn=None
        self.cursor=None
        self.after(1000, self.countdown_loop)

    def setup_timer_from_db(self):
        try:
            db_path=os.path.join(os.path.dirname(__file__), 'signtrack_web', 'instance', 'users.db')
            self.conn=sqlite3.connect(db_path)
            self.cursor=self.conn.cursor()
            today_str=datetime.now().strftime("%Y-%m-%d")
            self.cursor.execute("SELECT time_remaining, last_usage_reset FROM user WHERE id = ?", (self.logged_in_user_id,))
            row=self.cursor.fetchone()
            if row:
                saved_time, last_reset=row
                if saved_time is None or last_reset is None:
                    self.time_remaining=7200
                    self.save_timer_to_db()
                elif last_reset!=today_str:
                    self.time_remaining=7200
                    self.save_timer_to_db()
                else:
                    self.time_remaining=saved_time
            else:
                self.time_remaining=7200
                self.save_timer_to_db()
            self.reset_usage_if_needed()
        except Exception as e:
            messagebox.showerror("Timer Error", f"Usage DB error:\n{e}")
    def save_timer_to_db(self):
        today_str=datetime.now().strftime("%Y-%m-%d")
        self.cursor.execute(
            "UPDATE user SET time_remaining = ?, last_usage_reset = ? WHERE id = ?",
            (self.time_remaining, today_str, self.logged_in_user_id)
        )
        self.conn.commit()
    def countdown_loop(self):
        if not self.is_pro and self.signtrack_enabled.get():
            if self.time_remaining>0:
                self.time_remaining-=1
                self.save_timer_to_db()
                if self.timer_label and self.timer_label.winfo_exists():
                    mins, secs=divmod(self.time_remaining, 60)
                    self.timer_label.configure(text=f"⏳ Time Left: {mins:02d}:{secs:02d}")
            else:
                self.signtrack_enabled.set(False)
                self.toggle_signtrack()
                if self.timer_label and self.timer_label.winfo_exists():
                    self.timer_label.configure(text="❌ Time's up! Upgrade to Pro.")
        self.after(1000, self.countdown_loop)
    def update_pro_timer_display(self):
        if self.is_pro:
            if self.timer_label:
                self.timer_label.configure(text="✅ Unlimited Access")
            return
        if self.time_remaining>0:
            mins, secs=divmod(self.time_remaining, 60)
            self.timer_label.configure(text=f"⏳ Time Left: {mins:02d}:{secs:02d}")
        else:
            self.timer_label.configure(text="❌ Time's up! Upgrade to Pro.")
    def update_timer(self):
        if self.is_pro:
            return
        mins, secs=divmod(self.time_remaining, 60)
        time_str=f"{mins:02d}:{secs:02d}"
        self.timer_label.configure(text=f"⏳ Time Left: {time_str}")
        if self.time_remaining>0:
            self.time_remaining-=1
            self.after(1000, self.update_timer)
        else:
            self.timer_label.configure(text="❌ Time's up! Upgrade to Pro.")
    def set_position_bottom_right(self):
        screen_w=ctypes.windll.user32.GetSystemMetrics(0)
        screen_h=ctypes.windll.user32.GetSystemMetrics(1)
        self.geometry(f"480x400+{screen_w-480}+{screen_h-400}")
    def create_top_bar(self):
        self.top_bar=ctk.CTkFrame(self, height=30, fg_color="#1e1e1e")
        self.top_bar.pack(side="top", fill="x")
        self.top_bar.bind("<B1-Motion>", self.move_window)
        self.top_bar.bind("<Button-1>", self.get_pos)
        self.close_btn=ctk.CTkButton(
            self.top_bar, text="✕", width=30, height=24,
            fg_color="transparent", hover_color="#444",
            command=self.destroy, text_color=self.fg_color, font=("Arial", 14)
        )
        self.close_btn.pack(side="right", padx=(2, 10))
        self.minimize_btn=ctk.CTkButton(
            self.top_bar, text="–", width=30, height=24,
            fg_color="transparent", hover_color="#444",
            command=self.minimize_window, text_color=self.fg_color, font=("Arial", 14)
        )
        self.minimize_btn.pack(side="right")
    def minimize_window(self):
        self.overrideredirect(False)
        self.iconify()
    def on_restore(self, event):
        if self.state()=="normal":
            self.after(10, lambda: self.overrideredirect(True))
    def get_pos(self, event):
        self.xwin=event.x
        self.ywin=event.y
    def move_window(self, event):
        x=event.x_root-self.xwin
        y=event.y_root-self.ywin
        self.geometry(f"+{x}+{y}")
    def show_login(self):
        self.clear_screen()
        self.login_frame=ctk.CTkFrame(self, corner_radius=15)
        self.login_frame.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(self.login_frame, text="SignTrack Login", font=("Arial", 20, "bold"), text_color=self.fg_color).pack(pady=(10, 15))
        self.email_entry=ctk.CTkEntry(self.login_frame, placeholder_text="Email", width=220)
        self.email_entry.pack(pady=5)
        self.password_entry=ctk.CTkEntry(self.login_frame, placeholder_text="Password", show="*", width=220)
        self.password_entry.pack(pady=5)
        ctk.CTkButton(self.login_frame, text="Login", command=self.handle_login, text_color=self.fg_color).pack(pady=10)
    def handle_login(self):
        email=self.email_entry.get()
        password=self.password_entry.get()

        if not email or not password:
            messagebox.showwarning("Login Failed", "Please enter both email and password.")
            return

        try:
            db_path=os.path.join(os.path.dirname(__file__), 'signtrack_web', 'instance', 'users.db')
            print(f"Trying to connect to database at: {db_path}")

            if not os.path.exists(db_path):
                messagebox.showerror("Database Error", f"User database not found at:\n{db_path}")
                return

            conn=sqlite3.connect(db_path)
            cursor=conn.cursor()

            cursor.execute("SELECT id, password, status, pro_expiry FROM user WHERE email = ?", (email,))
            user=cursor.fetchone()
            conn.close()

            if not user:
                messagebox.showerror("Login Failed", f"User not found with email: {email}")
                return

            user_id, pw_hash, status, pro_expiry=user
            print(f"Found user: ID={user_id}, Status={status}")

            from werkzeug.security import check_password_hash
            if not check_password_hash(pw_hash, password):
                messagebox.showerror("Login Failed", "Incorrect password.")
                return

            self.logged_in_user_id=user_id
            self.is_pro=False

            if status=='pro' and pro_expiry:
                try:
                    expiry_date=datetime.strptime(pro_expiry, "%Y-%m-%d %H:%M:%S.%f")
                    if expiry_date>datetime.now():
                        self.is_pro=True
                        print("User has active Pro subscription")
                    else:
                        print("Pro subscription expired")
                except ValueError:
                    try:
                        expiry_date=datetime.strptime(pro_expiry, "%Y-%m-%d %H:%M:%S")
                        if expiry_date>datetime.now():
                            self.is_pro=True
                    except ValueError:
                        print("Could not parse pro_expiry date")

            if not self.is_pro:
                print("Setting up usage timer for free user")
                self.setup_timer_from_db()
            else:
                print("Pro user - no timer needed")

            messagebox.showinfo("Login Success", f"Welcome back! Status: {'Pro' if self.is_pro else 'Free'}")
            self.show_dashboard()

        except Exception as e:
            print(f"Login error: {e}")
            messagebox.showerror("Login Error", f"Database connection failed:\n{str(e)}")
    def reset_usage_if_needed(self):
        today_str=datetime.now().strftime("%Y-%m-%d")
        self.cursor.execute("SELECT last_usage_reset FROM user WHERE id = ?", (self.logged_in_user_id,))
        row=self.cursor.fetchone()

        if row and row[0]!=today_str:
            self.time_remaining=7200
            self.save_timer_to_db()
    def logout(self):
        self.signtrack_enabled.set(False)
        self.is_pro=False
        self.logged_in_user_id=None
        self.time_remaining=0
        self.clear_screen()
        self.show_login()

    def show_dashboard(self):
        self.clear_screen()
        self.sidebar=ctk.CTkFrame(self, width=50, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.main_area=ctk.CTkFrame(self, corner_radius=15)
        self.main_area.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.create_nav_button("🏠", self.load_home).pack(pady=(20, 10))
        self.create_nav_button("⚙️", self.load_settings).pack(pady=10)
        self.create_nav_button("💎", self.load_pro).pack(pady=10)
        self.load_home()
    def create_nav_button(self, icon, command):
        return ctk.CTkButton(self.sidebar, text=icon, width=40, height=40,
                             font=("Arial", 16), command=command,
                             fg_color="transparent", hover_color="#333", text_color=self.fg_color)
    def load_home(self):
        self.clear_main()
        ctk.CTkLabel(self.main_area, text="SignTrack Toggle", font=("Arial", 16), text_color=self.fg_color).pack(pady=20)
        toggle=ctk.CTkSwitch(self.main_area, text="SignTrack On/Off", text_color=self.fg_color,
                               variable=self.signtrack_enabled, command=self.toggle_signtrack)
        toggle.pack(pady=10)
        ctk.CTkLabel(self.main_area, text="Gesture Controls", font=("Arial", 14, "bold"), text_color=self.fg_color).pack(pady=(15, 5))
        gesture_text=(
            "👊 Fist           — Left Click\n"
            "🖐️ Five Fingers   — Right Click\n"
            "☝️ One Finger     — Move Cursor\n"
            "✌️ Two Fingers    — Scroll\n"
            "👍 Thumbs Up      — Switch Tab (Alt+Tab)\n"
            "👎 Thumbs Down    — Close Tab"
        )
        ctk.CTkLabel(self.main_area, text=gesture_text, justify="left", font=("Courier", 13), text_color=self.fg_color).pack(pady=10)
    def load_settings(self):
        self.clear_main()
        ctk.CTkLabel(self.main_area, text="Settings", font=("Arial", 16), text_color=self.fg_color).pack(pady=10)
        ctk.CTkLabel(self.main_area, text="Preview Corner", text_color=self.fg_color).pack(pady=(10, 0))
        ctk.CTkOptionMenu(self.main_area, values=list(CORNER_MAPPING.keys()),
                          variable=self.preview_corner, text_color=self.fg_color).pack()
        ctk.CTkLabel(self.main_area, text="Preview Size", text_color=self.fg_color).pack(pady=(10, 0))
        ctk.CTkSlider(self.main_area, from_=100, to=300, variable=self.preview_size).pack()
        ctk.CTkLabel(self.main_area, text="Show Preview", text_color=self.fg_color).pack(pady=(10, 0))
        ctk.CTkSwitch(self.main_area, variable=self.show_preview, text="Toggle Preview", text_color=self.fg_color).pack()
        ctk.CTkLabel(self.main_area, text="Account", text_color=self.fg_color).pack(pady=(20, 0))
        ctk.CTkButton(self.main_area, text="Logout", command=self.logout, text_color="red").pack(pady=5)

    def load_pro(self):
        self.clear_main()
        ctk.CTkLabel(self.main_area, text="Pro Version", font=("Arial", 16, "bold"), text_color=self.fg_color).pack(pady=10)
        ctk.CTkLabel(self.main_area, text="• Unlimited usage\n• Full features\n• Priority Support", text_color=self.fg_color).pack(pady=10)
        if self.is_pro:
            ctk.CTkLabel(self.main_area, text="✅ Unlimited Access", font=("Arial", 14), text_color="green").pack(pady=10)
        else:
            self.timer_label=ctk.CTkLabel(self.main_area, text="", font=("Arial", 14), text_color="orange")
            self.timer_label.pack(pady=10)
            self.update_pro_timer_display()
            ctk.CTkButton(self.main_area, text="Buy Pro", command=self.open_web_buy_page, text_color=self.fg_color).pack(pady=10)
            ctk.CTkButton(self.main_area, text="Refresh", command=self.refresh_pro_status, text_color=self.fg_color).pack(pady=5)
    def open_web_buy_page(self):
        import webbrowser
        webbrowser.open("http://localhost:5000/login")
    def activate_pro(self):
        self.is_pro=True
        self.load_pro()
    def refresh_pro_status(self):
        try:
            db_path=os.path.join(os.path.dirname(__file__), 'signtrack_web', 'instance', 'users.db')
            print("Using DB Path:", db_path)
            if not os.path.exists(db_path):
                messagebox.showerror("Database Error", f"Database not found:\n{db_path}")
                return
            conn=sqlite3.connect(db_path)
            cursor=conn.cursor()
            cursor.execute("SELECT status, pro_expiry FROM user WHERE id = ?", (self.logged_in_user_id,))
            row=cursor.fetchone()
            conn.close()
            if not row:
                messagebox.showerror("Error", "User not found.")
                return
            status, pro_expiry=row
            self.is_pro=False
            if status=='pro' and pro_expiry:
                expiry_date=datetime.strptime(pro_expiry, "%Y-%m-%d %H:%M:%S.%f")
                if expiry_date>datetime.now():
                    self.is_pro=True
            self.load_pro()
        except Exception as e:
            messagebox.showerror("Refresh Failed", f"Unable to open database:\n{e}")
    def toggle_signtrack(self):
        if self.signtrack_enabled.get():
            if not self.is_pro and self.time_remaining<=0:
                messagebox.showwarning("Limit Reached", "Free usage limit reached. Please upgrade to Pro.")
                self.signtrack_enabled.set(False)
                return
            self.stop_thread.clear()
            self.gesture_thread=threading.Thread(target=self.run_gesture_control)
            self.gesture_thread.start()
        else:
            self.stop_thread.set()
    def run_gesture_control(self):
        cap=cv2.VideoCapture(0)
        while not self.stop_thread.is_set():
            ret, frame=cap.read()
            if not ret:
                continue
            img=cv2.flip(frame, 1)
            img_rgb=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            result=hands.process(img_rgb)

            current_gesture=None
            if result.multi_hand_landmarks:
                hand_landmarks=result.multi_hand_landmarks[0]
                self.latest_landmarks=hand_landmarks.landmark
                self.img_shape=img.shape
                h, w, _=img.shape
                x_coords=[lm.x*w for lm in hand_landmarks.landmark]
                y_coords=[lm.y*h for lm in hand_landmarks.landmark]
                x_min, x_max=int(min(x_coords)), int(max(x_coords))
                y_min, y_max=int(min(y_coords)), int(max(y_coords))
                x_min, y_min=max(x_min-20, 0), max(y_min-20, 0)
                x_max, y_max=min(x_max+20, w), min(y_max+20, h)
                roi=img[y_min:y_max, x_min:x_max]
                if roi.size==0:
                    continue
                roi_resized=cv2.resize(roi, (IMG_SIZE, IMG_SIZE))
                roi_rgb=cv2.cvtColor(roi_resized, cv2.COLOR_BGR2RGB)
                roi_normalized=roi_rgb/255.0
                roi_expanded=np.expand_dims(roi_normalized, axis=0)
                pred=model.predict(roi_expanded, verbose=0)[0]

                predicted_gesture=CLASS_NAMES[np.argmax(pred)]
                if np.max(pred)>GESTURE_THRESHOLDS[predicted_gesture]:
                    current_gesture=predicted_gesture
                    self.perform_action(current_gesture)

            global thumbs_up_held
            if thumbs_up_held and current_gesture!='thumbs_up':
                keyboard.release('alt')
                thumbs_up_held=False

            if self.show_preview.get():
                corner=CORNER_MAPPING[self.preview_corner.get()]
                preview_w=int(self.preview_size.get())
                preview_h=int(preview_w*img.shape[0]/img.shape[1])
                work_area=ctypes.wintypes.RECT()
                SPI_GETWORKAREA=0x0030
                ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work_area), 0)
                screen_w=work_area.right
                screen_h=work_area.bottom
                x=0 if corner[0]==0 else screen_w-preview_w
                y=0 if corner[1]==0 else screen_h-preview_h
                resized=cv2.resize(img, (preview_w, preview_h))
                if not self.preview_initialized:
                    cv2.namedWindow("SignTrack Preview", cv2.WINDOW_NORMAL)
                    cv2.setWindowProperty("SignTrack Preview", cv2.WND_PROP_TOPMOST, 1)
                    self.preview_initialized=True
                cv2.resizeWindow("SignTrack Preview", preview_w, preview_h)
                cv2.imshow("SignTrack Preview", resized)
                cv2.moveWindow("SignTrack Preview", x, y)
            else:
                if cv2.getWindowProperty("SignTrack Preview", cv2.WND_PROP_VISIBLE)>=1:
                    cv2.destroyWindow("SignTrack Preview")
                    self.preview_initialized=False
            if cv2.waitKey(1)&0xFF==27:
                break
        cap.release()
        cv2.destroyAllWindows()
    def map_hand_to_screen(self, hand_x, hand_y, gesture_type="normal"):
        global last_cursor_x, last_cursor_y

        screen_w, screen_h=pyautogui.size()

        horizontal_margin=0.2
        if gesture_type=="one_finger":
            normalized_y=hand_y*2
            horizontal_margin=0.1
        else:
            normalized_y=(hand_y-horizontal_margin)/(1-2*horizontal_margin)
        normalized_x=(hand_x-horizontal_margin)/(1-2*horizontal_margin)

        normalized_x=max(0, min(1, normalized_x))
        normalized_y=max(0, min(1, normalized_y))

        target_x=int(normalized_x*screen_w)
        target_y=int(normalized_y*screen_h)

        if last_cursor_x!=0 and last_cursor_y!=0:
            target_x=int(last_cursor_x*cursor_smoothing+target_x*(1-cursor_smoothing))
            target_y=int(last_cursor_y*cursor_smoothing+target_y*(1-cursor_smoothing))

        last_cursor_x=target_x
        last_cursor_y=target_y

        return target_x, target_y
    def perform_action(self, gesture):
        global thumbs_up_held, thumbs_up_position, last_tab_switch_time
        global thumbs_down_last_time, scrolling_up, scrolling_down
        current_time=time.time()

        if gesture in last_gesture_times:
            if current_time-last_gesture_times[gesture]<cooldown_times[gesture]:
                return

        if gesture=='one_finger' and self.latest_landmarks:
            finger_x=self.latest_landmarks[8].x
            finger_y=self.latest_landmarks[8].y

            screen_x, screen_y=self.map_hand_to_screen(finger_x, finger_y, "one_finger")

            pyautogui.moveTo(screen_x, screen_y)
            last_gesture_times['one_finger']=current_time

        elif gesture=='fist':
            pyautogui.click(button='left')
            last_gesture_times['fist']=current_time

        elif gesture=='five_fingers':
            pyautogui.click(button='right')
            last_gesture_times['five_fingers']=current_time

        elif gesture=='two_fingers' and self.latest_landmarks:
            finger_y=self.latest_landmarks[8].y

            if finger_y<0.4:
                if not scrolling_up:
                    scrolling_up=True
                    scrolling_down=False
                pyautogui.scroll(10)
            elif finger_y>0.6:
                if not scrolling_down:
                    scrolling_down=True
                    scrolling_up=False
                pyautogui.scroll(-10)

            last_gesture_times['two_fingers']=current_time

        elif gesture=='thumbs_up' and self.latest_landmarks and self.img_shape:
            thumb_x_pixel=self.latest_landmarks[4].x*self.img_shape[1]
            if not thumbs_up_held:
                keyboard.press('alt')
                keyboard.press('tab')
                keyboard.release('tab')
                thumbs_up_held=True
                thumbs_up_position=thumb_x_pixel
                last_tab_switch_time=current_time
            else:
                delta_x=thumb_x_pixel-thumbs_up_position

                if current_time-last_tab_switch_time>tab_switch_cooldown:
                    if delta_x>THUMBS_UP_HORIZONTAL_THRESHOLD_PIXELS:
                        keyboard.press('tab')
                        keyboard.release('tab')
                        thumbs_up_position=thumb_x_pixel
                        last_tab_switch_time=current_time
                    elif delta_x<-THUMBS_UP_HORIZONTAL_THRESHOLD_PIXELS:
                        keyboard.press('shift')
                        keyboard.press('tab')
                        keyboard.release('tab')
                        keyboard.release('shift')
                        thumbs_up_position=thumb_x_pixel
                        last_tab_switch_time=current_time
                    last_gesture_times['thumbs_up']=current_time

        elif gesture=='thumbs_down':
            if current_time-thumbs_down_last_time>1:
                keyboard.press_and_release('alt+f4')
                thumbs_down_last_time=current_time

            last_gesture_times['thumbs_down']=current_time
    def clear_main(self):
        for widget in self.main_area.winfo_children():
            widget.destroy()
    def clear_screen(self):
        for widget in self.winfo_children():
            if widget!=self.top_bar:
                widget.destroy()
if __name__=="__main__":
    app=SignTrackApp()
    app.mainloop()