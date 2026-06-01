import os
import threading
import requests
import tkinter as tk
from tkinter import ttk, messagebox
import logging
from PyPDF2 import PdfMerger
import math
from io import BytesIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_access_token(client_id, client_secret):
    url = 'https://api-production.boxnow.bg/api/v1/auth-sessions'
    payload = {'grant_type': 'client_credentials', 'client_id': client_id, 'client_secret': client_secret}
    response = requests.post(url, json=payload, timeout=30)
    if response.status_code == 200:
        return response.json()['access_token']
    else:
        raise Exception(f'Failed to authenticate: {response.status_code}')

def prepare_folder(folder_name):
    folder_path = os.path.join(os.getcwd(), folder_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path

def download_selected_labels(selected_ids, access_token, folder_path, output_filename, paper_size='A4', per_page=1):
    url = 'https://api-production.boxnow.bg/api/v1/labels:search'
    payload = {'parcelIds': [str(pid) for pid in selected_ids], 'paperSize': paper_size, 'perPage': per_page}
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    response = requests.post(url, json=payload, headers=headers, timeout=120)
    if response.status_code == 200:
        with open(os.path.join(folder_path, output_filename), 'wb') as file:
            file.write(response.content)
    else:
        try:
            error_json = response.json()
            msg = error_json.get('message', '').lower()
            if 'paper size' in msg or 'unsupported' in msg or 'not supported' in msg or 'invalid' in msg:
                messagebox.showerror('Грешка', f'Избраният формат на хартията ({paper_size}) не се поддържа от API! Моля, изберете друг формат (най-вероятно само A4 работи).')
                return False
        except Exception:
            pass
        messagebox.showerror('Грешка', f'Неуспешно изтегляне на етикети: {response.status_code}')
        return False
    return True

def fetch_parcel_ids(access_token):
    url = 'https://api-production.boxnow.bg/api/v1/parcels'
    headers = {'Authorization': f'Bearer {access_token}'}

    all_ids = []
    seen_ids = set()
    next_cursor = None

    while True:
        params = {'state': 'new'}
        if next_cursor:
            params['pageToken'] = next_cursor

        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            raise Exception(f'Failed to fetch data: {response.status_code}')

        data = response.json()
        items = data.get('data', [])

        if not items:
            break

        new_ids = [p['id'] for p in items if p['id'] not in seen_ids]
        if not new_ids:
            break

        all_ids.extend(new_ids)
        seen_ids.update(new_ids)

        pagination = data.get('pagination') or {}
        next_cursor = pagination.get('next')
        first_cursor = pagination.get('first')

        # Stop when there is no next page, or next loops back to the first page
        if not next_cursor or next_cursor == first_cursor:
            break

    return all_ids

def start_single_label_mode(access_token):
    folder_path = prepare_folder('new_single')

    loading_win = tk.Toplevel(window)
    loading_win.title('Зареждане...')
    loading_win.geometry('300x80')
    loading_win.resizable(False, False)
    tk.Label(loading_win, text='Зареждане на пратки, моля изчакайте...', font=('Arial', 11)).pack(expand=True)

    def do_fetch():
        try:
            parcel_ids = fetch_parcel_ids(access_token)
            window.after(0, lambda ids=parcel_ids: show_selection(ids))
        except Exception as e:
            err_msg = str(e)
            window.after(0, lambda msg=err_msg: on_fetch_error(msg))

    def on_fetch_error(msg):
        loading_win.destroy()
        messagebox.showerror('Грешка', f'Грешка при извличане на данни: {msg}')

    def show_selection(parcel_ids):
        loading_win.destroy()

        selection_window = tk.Toplevel(window)
        tk.Label(selection_window, text='Моля, изберете номера на пратките, за които искате да изтеглите етикети', font=('Arial', 12, 'bold'), bg='#6cd04e', fg='white').pack(pady=10)
        selection_window.geometry('1300x900')
        selection_window.title('Избор на пратки')
        selection_window.configure(bg='#6cd04e')
        selection_canvas = tk.Canvas(selection_window)
        selection_scrollbar = tk.Scrollbar(selection_window, orient='vertical', command=selection_canvas.yview)
        scrollable_frame = tk.Frame(selection_canvas)

        scrollable_frame.bind(
            '<Configure>',
            lambda e: selection_canvas.configure(scrollregion=selection_canvas.bbox('all'))
        )

        selection_canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')
        selection_canvas.configure(yscrollcommand=selection_scrollbar.set)

        def on_mouse_scroll(event):
            selection_canvas.yview_scroll(-1 * (event.delta // 120), 'units')

        selection_canvas.bind_all('<MouseWheel>', on_mouse_scroll)
        selection_canvas.pack(side='left', fill='both', expand=True)
        selection_scrollbar.pack(side='right', fill='y')

        checkboxes = []
        columns = 4
        rows_per_column = 25
        col_index = 0
        row_index = 0

        for parcel_id in parcel_ids:
            var = tk.BooleanVar()
            cb = tk.Checkbutton(scrollable_frame, text=parcel_id, variable=var, fg='black', font=('Arial', 10, 'bold'))
            checkboxes.append((parcel_id, var))

            def make_toggle(c, v):
                def toggle(*args):
                    c.config(fg='#6cd04e' if v.get() else 'black')
                return toggle

            var.trace_add('write', make_toggle(cb, var))
            cb.grid(row=row_index, column=col_index, sticky='w', padx=5, pady=2)
            row_index += 1
            if row_index >= rows_per_column:
                row_index = 0
                col_index += 1

        def download_selected():
            selected_ids = [pid for pid, var in checkboxes if var.get()]
            if not selected_ids:
                messagebox.showwarning('Внимание', 'Няма избрани пратки!')
                return

            options_window = tk.Toplevel(selection_window)
            tk.Label(options_window, text='Моля, изберете размер на хартията и колко етикета да има на всеки лист', font=('Arial', 12, 'bold'), bg='#6cd04e', fg='white').pack(pady=10)
            options_window.title('Опции за етикети')
            options_window.geometry('600x300')

            tk.Label(options_window, text='Размер на хартия:').pack(pady=5)
            paper_size_var = tk.StringVar(value='A4')
            ttk.Combobox(options_window, textvariable=paper_size_var, values=['A4', 'A6']).pack(pady=5)

            tk.Label(options_window, text='На лист:').pack(pady=5)
            per_page_var = tk.StringVar(value='1')
            ttk.Combobox(options_window, textvariable=per_page_var, values=['1', '2', '3', '4']).pack(pady=5)

            confirm_btn = tk.Button(options_window, text='Потвърди и изтегли', bg='#009B4D', fg='white', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5)
            confirm_btn.pack(pady=10)

            def confirm_and_download():
                paper_size = paper_size_var.get()
                per_page = int(per_page_var.get())
                confirm_btn.config(state='disabled', text='Изтегляне...')

                def do_download():
                    ok = download_selected_labels(selected_ids, access_token, folder_path, 'single_new_labels.pdf', paper_size, per_page)
                    window.after(0, lambda: on_done(ok))

                def on_done(ok):
                    if ok:
                        messagebox.showinfo('Успех', f'Избраните етикети са изтеглени в {folder_path}')
                        options_window.destroy()
                        selection_window.destroy()
                        window.quit()
                    else:
                        confirm_btn.config(state='normal', text='Потвърди и изтегли')

                threading.Thread(target=do_download, daemon=True).start()

            confirm_btn.config(command=confirm_and_download)

        tk.Button(selection_window, text='Изтегли избраните', command=download_selected).place(x=10, y=10)

    threading.Thread(target=do_fetch, daemon=True).start()

def cancel_parcel(parcel_id, access_token):
    url = f'https://api-production.boxnow.bg/api/v1/parcels/{parcel_id}:cancel'
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    response = requests.post(url, json={}, headers=headers, timeout=30)
    return response.status_code in (200, 204)

def start_cancel_all_mode(access_token):
    if not messagebox.askyesno(
        'Потвърждение',
        'Сигурни ли сте, че искате да анулирате ВСИЧКИ пратки със статус "нова"?\n\nТова действие не може да бъде отменено!'
    ):
        return

    progress_win = tk.Toplevel(window)
    progress_win.title('Анулиране на пратки...')
    progress_win.geometry('400x150')
    progress_win.resizable(False, False)
    progress_win.configure(bg='#6cd04e')

    status_label = tk.Label(progress_win, text='Зареждане на пратки...', font=('Arial', 11), bg='#6cd04e', fg='white')
    status_label.pack(pady=15)

    progress_bar = ttk.Progressbar(progress_win, length=340, mode='determinate')
    progress_bar.pack(pady=5)

    count_label = tk.Label(progress_win, text='', font=('Arial', 10), bg='#6cd04e', fg='white')
    count_label.pack(pady=5)

    def do_cancel():
        try:
            parcel_ids = fetch_parcel_ids(access_token)
            total = len(parcel_ids)

            if total == 0:
                window.after(0, lambda: on_done(0, 0))
                return

            window.after(0, lambda: progress_bar.config(maximum=total))
            succeeded = 0
            failed = 0

            for i, pid in enumerate(parcel_ids):
                ok = cancel_parcel(pid, access_token)
                if ok:
                    succeeded += 1
                else:
                    failed += 1

                done = i + 1
                window.after(0, lambda d=done, s=succeeded, f=failed: (
                    progress_bar.config(value=d),
                    status_label.config(text=f'Анулиране: {d}/{total}'),
                    count_label.config(text=f'Успешни: {s}  |  Неуспешни: {f}')
                ))

            window.after(0, lambda s=succeeded, f=failed: on_done(s, f))

        except Exception as e:
            err_msg = str(e)
            window.after(0, lambda msg=err_msg: on_error(msg))

    def on_done(succeeded, failed):
        progress_win.destroy()
        if failed == 0:
            messagebox.showinfo('Успех', f'Всички {succeeded} пратки бяха анулирани успешно.')
        else:
            messagebox.showwarning('Завършено', f'Анулирани: {succeeded}\nНеуспешни: {failed}')

    def on_error(msg):
        progress_win.destroy()
        messagebox.showerror('Грешка', f'Грешка при анулиране: {msg}')

    threading.Thread(target=do_cancel, daemon=True).start()

def start_all_labels_mode(access_token):
    folder_path = prepare_folder('new')
    options_window = tk.Toplevel(window)
    tk.Label(options_window, text='Моля, изберете размер на хартията и колко етикета да има на всеки лист', font=('Arial', 12, 'bold'), bg='#6cd04e', fg='white').pack(pady=10)
    options_window.title('Опции за етикети')
    options_window.geometry('600x300')

    tk.Label(options_window, text='Размер на хартия:').pack(pady=5)
    paper_size_var = tk.StringVar(value='A4')
    ttk.Combobox(options_window, textvariable=paper_size_var, values=['A4', 'A6']).pack(pady=5)

    tk.Label(options_window, text='На лист:').pack(pady=5)
    per_page_var = tk.StringVar(value='1')
    ttk.Combobox(options_window, textvariable=per_page_var, values=['1', '2', '3', '4']).pack(pady=5)

    confirm_btn = tk.Button(options_window, text='Потвърди и изтегли', bg='#009B4D', fg='white', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5)
    confirm_btn.pack(pady=10)

    def download_all_with_options():
        paper_size = paper_size_var.get()
        per_page = int(per_page_var.get())
        confirm_btn.config(state='disabled', text='Изтегляне...')

        def do_work():
            try:
                parcel_ids = fetch_parcel_ids(access_token)
                ok = download_selected_labels(parcel_ids, access_token, folder_path, 'all_new_labels.pdf', paper_size, per_page)
                window.after(0, lambda result=ok: on_done(result))
            except Exception as e:
                err_msg = str(e)
                window.after(0, lambda msg=err_msg: on_error(msg))

        def on_done(ok):
            if ok:
                messagebox.showinfo('Успех', f'Всички етикети са изтеглени в {folder_path}')
                options_window.destroy()
                window.quit()
            else:
                confirm_btn.config(state='normal', text='Потвърди и изтегли')

        def on_error(msg):
            confirm_btn.config(state='normal', text='Потвърди и изтегли')
            messagebox.showerror('Грешка', f'Грешка при извличане на данни: {msg}')

        threading.Thread(target=do_work, daemon=True).start()

    confirm_btn.config(command=download_all_with_options)

def authenticate():
    client_id = client_id_entry.get().strip()
    client_secret = client_secret_entry.get().strip()

    if not client_id or not client_secret:
        messagebox.showerror('Грешка', 'Клиент ID и Клиент Secret не могат да бъдат празни. Моля, проверете въведените данни.')
        return

    start_button.config(state='disabled', text='Влизане...')

    def do_auth():
        try:
            access_token = get_access_token(client_id, client_secret)
            window.after(0, lambda tok=access_token: on_auth_success(tok))
        except Exception as e:
            err_msg = str(e)
            window.after(0, lambda msg=err_msg: on_auth_error(msg))

    def on_auth_success(access_token):
        start_button.pack_forget()
        client_id_label.pack_forget()
        client_id_entry.pack_forget()
        client_secret_label.pack_forget()
        client_secret_entry.pack_forget()

        tk.Button(window, text='Етикет за една пратка', command=lambda: start_single_label_mode(access_token), bg='white', fg='#009B4D', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5).pack(pady=5)
        tk.Button(window, text='Етикети за всички пратки', command=lambda: start_all_labels_mode(access_token), bg='white', fg='#009B4D', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5).pack(pady=5)
        tk.Button(window, text='Анулирай всички нови пратки', command=lambda: start_cancel_all_mode(access_token), bg='#cc0000', fg='white', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5).pack(pady=5)

    def on_auth_error(msg):
        start_button.config(state='normal', text='Вход')
        messagebox.showerror('Грешка при оторизация', f'Възникна грешка при оторизацията. Моля, проверете вашите данни и се уверете, че няма излишни интервали.\n\nГрешка: {msg}')

    threading.Thread(target=do_auth, daemon=True).start()

window = tk.Tk()
window.geometry('800x600')
window.title('BoxNow Label Fetcher v9 - Българска версия')
window.configure(bg='#6cd04e')

image_path = os.path.join(os.path.dirname(__file__), 'BoxNow.png')
with open(image_path, 'rb') as logo_file:
    logo_image = tk.PhotoImage(data=BytesIO(logo_file.read()).read())

logo_label = tk.Label(window, image=logo_image)
logo_label.pack(pady=10)

client_id_label = tk.Label(window, text='Клиент ID:', bg='#009B4D', fg='white', font=('Arial', 12, 'bold'))
client_id_label.pack()
client_id_entry = tk.Entry(window, width=40)
client_id_entry.pack(pady=5)

client_secret_label = tk.Label(window, text='Клиент Secret:', bg='#009B4D', fg='white', font=('Arial', 12, 'bold'))
client_secret_label.pack()
client_secret_entry = tk.Entry(window, width=40, show='*')
client_secret_entry.pack(pady=5)

start_button = tk.Button(window, text='Вход', command=authenticate, bg='white', fg='#009B4D', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5)
start_button.pack(pady=10)

window.logo_image = logo_image
window.mainloop()
