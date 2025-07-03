import os
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
    response = requests.post(url, json=payload)
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
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        with open(os.path.join(folder_path, output_filename), 'wb') as file:
            file.write(response.content)
    else:
        # Check for unsupported paper size
        try:
            error_json = response.json()
            msg = error_json.get('message', '').lower()
            if 'paper size' in msg or 'unsupported' in msg or 'not supported' in msg or 'invalid' in msg:
                import tkinter.messagebox as messagebox
                messagebox.showerror('Грешка', f'Избраният формат на хартията ({paper_size}) не се поддържа от API! Моля, изберете друг формат (най-вероятно само A4 работи).')
                return False
        except Exception:
            pass
        import tkinter.messagebox as messagebox
        messagebox.showerror('Грешка', f'Неуспешно изтегляне на етикети: {response.status_code}')
        return False
    return True

def fetch_parcel_ids(access_token):
    url = 'https://api-production.boxnow.bg/api/v1/parcels?state=new'
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        total_count = int(data['count'])
        total_pages = math.ceil(total_count / 50)
        all_data = []
        next_page_token = None
        for page in range(total_pages):
            params = {'pageToken': next_page_token} if next_page_token else {}
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                all_data.extend(data['data'])
                next_page_token = data['pagination'].get('next')
            else:
                raise Exception(f'Failed to fetch data: {response.status_code}')
        return [parcel['id'] for parcel in all_data]
    else:
        raise Exception(f'Failed to fetch parcel IDs: {response.status_code}')

def start_single_label_mode(access_token):
    folder_path = prepare_folder('new_single')
    
    parcel_ids = fetch_parcel_ids(access_token)
    

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
        lambda e: selection_canvas.configure(
            scrollregion=selection_canvas.bbox('all')
        )
    )

    selection_canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')
    selection_canvas.configure(yscrollcommand=selection_scrollbar.set)

    # Enable mouse scrolling with the scroll wheel
    def on_mouse_scroll(event):
        selection_canvas.yview_scroll(-1 * (event.delta // 120), 'units')

    selection_canvas.bind_all('<MouseWheel>', on_mouse_scroll)

    selection_canvas.pack(side='left', fill='both', expand=True)
    selection_scrollbar.pack(side='right', fill='y')

    selection_window.geometry('1300x900')
    selection_window.title('Избор на пратки')
    selected_vars = {}
    checkboxes = []

    columns = 4  # Number of columns
    rows_per_column = 25  # IDs per column
    col_index = 0
    row_index = 0
    
    for parcel_id in parcel_ids:
        var = tk.BooleanVar()
        checkboxes.append((parcel_id, var))
        cb = tk.Checkbutton(scrollable_frame, text=parcel_id, variable=var, fg='black', font=('Arial', 10, 'bold'))
        
        def toggle_color(c=cb, v=var):
            c.config(fg='#6cd04e' if v.get() else 'black')
        
        var.trace_add('write', lambda *args, c=cb, v=var: toggle_color(c, v))
        def toggle_color(cb=cb, var=var):
            cb.config(fg='#6cd04e' if var.get() else 'black')
        var = tk.BooleanVar()
        
        cb.grid(row=row_index, column=col_index, sticky='w', padx=5, pady=2)
        row_index += 1
        if row_index >= rows_per_column:
            row_index = 0
            col_index += 1
        selected_vars[parcel_id] = var

    def download_selected():
        selected_ids = [pid for pid, var in checkboxes if var.get()]
        if not selected_ids:
            messagebox.showwarning('Внимание', 'Няма избрани пратки!')
            return

        # Open a new window to select paperSize and perPage
        options_window = tk.Toplevel(selection_window)
        tk.Label(options_window, text='Моля, изберете размер на хартията и колко етикета да има на всеки лист', font=('Arial', 12, 'bold'), bg='#6cd04e', fg='white').pack(pady=10)
        options_window.title('Опции за етикети')
        options_window.geometry('600x300')

        tk.Label(options_window, text='Размер на хартия:').pack(pady=5)
        paper_size_var = tk.StringVar(value='A4')
        paper_size_dropdown = ttk.Combobox(options_window, textvariable=paper_size_var, values=['A4', 'A6'])
        paper_size_dropdown.pack(pady=5)

        tk.Label(options_window, text='На лист:').pack(pady=5)
        per_page_var = tk.StringVar(value='1')
        per_page_dropdown = ttk.Combobox(options_window, textvariable=per_page_var, values=['1', '2', '3', '4'])
        per_page_dropdown.pack(pady=5)

        def confirm_and_download():
            paper_size = paper_size_var.get()
            per_page = int(per_page_var.get())
            ok = download_selected_labels(selected_ids, access_token, folder_path, 'single_new_labels.pdf', paper_size, per_page)
            if ok:
                messagebox.showinfo('Успех', f'Избраните етикети са изтеглени в {folder_path}')
                options_window.destroy()
                selection_window.destroy()
                window.quit()

        tk.Button(options_window, text='Потвърди и изтегли', command=confirm_and_download, bg='#009B4D', fg='white', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5).pack(pady=10)

    tk.Button(selection_window, text='Изтегли избраните', command=download_selected).place(x=10, y=10)

def start_all_labels_mode(access_token):
    def download_all_with_options():
        paper_size = paper_size_var.get()
        per_page = int(per_page_var.get())
        parcel_ids = fetch_parcel_ids(access_token)
        ok = download_selected_labels(parcel_ids, access_token, folder_path, 'all_new_labels.pdf', paper_size, per_page)
        if ok:
            messagebox.showinfo('Успех', f'Всички етикети са изтеглени в {folder_path}')
            options_window.destroy()
            window.quit()

    folder_path = prepare_folder('new')
    options_window = tk.Toplevel(window)
    tk.Label(options_window, text='Моля, изберете размер на хартията и колко етикета да има на всеки лист', font=('Arial', 12, 'bold'), bg='#6cd04e', fg='white').pack(pady=10)
    options_window.title('Опции за етикети')
    options_window.geometry('600x300')

    tk.Label(options_window, text='Размер на хартия:').pack(pady=5)
    paper_size_var = tk.StringVar(value='A4')
    paper_size_dropdown = ttk.Combobox(options_window, textvariable=paper_size_var, values=['A4', 'A6'])
    paper_size_dropdown.pack(pady=5)

    tk.Label(options_window, text='На лист:').pack(pady=5)
    per_page_var = tk.StringVar(value='1')
    per_page_dropdown = ttk.Combobox(options_window, textvariable=per_page_var, values=['1', '2', '3', '4'])
    per_page_dropdown.pack(pady=5)

    tk.Button(options_window, text='Потвърди и изтегли', command=download_all_with_options, bg='#009B4D', fg='white', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5).pack(pady=10)

    

def authenticate():
    client_id = client_id_entry.get().strip()
    client_secret = client_secret_entry.get().strip()
    
    if not client_id or not client_secret:
        messagebox.showerror('Грешка', 'Клиент ID и Клиент Secret не могат да бъдат празни. Моля, проверете въведените данни.')
        return
    
    try:
        access_token = get_access_token(client_id, client_secret)
    except Exception as e:
        messagebox.showerror('Грешка при оторизация', f'Възникна грешка при оторизацията. Моля, проверете вашите данни и се уверете, че няма излишни интервали.\n\nГрешка: {str(e)}')
        return
    # Скриване на бутона за вход
    start_button.pack_forget()
    client_id_label.pack_forget()
    client_id_entry.pack_forget()
    client_secret_label.pack_forget()
    client_secret_entry.pack_forget()
    # Показване само на двата бутона за товарителници
    tk.Button(window, text='Етикет за една пратка', command=lambda: start_single_label_mode(access_token), bg='white', fg='#009B4D', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5).pack(pady=5)
    tk.Button(window, text='Етикети за всички пратки', command=lambda: start_all_labels_mode(access_token), bg='white', fg='#009B4D', font=('Arial', 12, 'bold'), relief='flat', padx=10, pady=5).pack(pady=5)

window = tk.Tk()
window.geometry('800x600')
window.title('BoxNow Label Fetcher')
window.configure(bg='#6cd04e')

# Load and display logo from absolute path
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

window.mainloop()

# Keep reference to the image
window.logo_image = logo_image
