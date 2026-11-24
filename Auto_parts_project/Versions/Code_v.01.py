import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

class AutoShopDB:
    """Слой работы с базой данных (SQLite)"""
    def __init__(self, db_name="autoshop.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        with self.conn:
            # Справочник товаров и текущий остаток
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE,
                    name TEXT,
                    category TEXT,
                    price REAL,
                    current_qty INTEGER
                )
            """)
            # Журнал смен
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TEXT,
                    end_time TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            # Снимок остатков и продаж за смену
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS shift_details (
                    shift_id INTEGER,
                    product_id INTEGER,
                    initial_qty INTEGER,
                    sold_qty INTEGER DEFAULT 0,
                    final_qty INTEGER,
                    PRIMARY KEY(shift_id, product_id)
                )
            """)
            self.seed_sample_data()

    def seed_sample_data(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM inventory")
        if cursor.fetchone()[0] == 0:
            sample = [
                ("A-001", "Масло моторное 5W-40 4L", "Масла", 2500.0, 5),
                ("A-002", "Фильтр масляный W712", "Фильтры", 450.0, 10),
                ("A-003", "Колодки тормозные передние", "Тормозная система", 1800.0, 3),
                ("A-004", "Свеча зажигания Nickel", "Зажигание", 350.0, 16),
                ("A-005", "Антифриз G12+ 5L", "Охлаждение", 1200.0, 4)
            ]
            self.conn.executemany(
                "INSERT INTO inventory (sku, name, category, price, current_qty) VALUES (?, ?, ?, ?, ?)",
                sample
            )
            self.conn.commit()

    def get_active_shift(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, start_time FROM shifts WHERE is_active = 1")
        return cursor.fetchone()

    def open_shift(self):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("INSERT INTO shifts (start_time, is_active) VALUES (?, 1)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
            shift_id = cursor.lastrowid
            
            cursor.execute("SELECT id, current_qty FROM inventory")
            items = cursor.fetchall()
            for prod_id, qty in items:
                cursor.execute(
                    "INSERT INTO shift_details (shift_id, product_id, initial_qty, sold_qty, final_qty) VALUES (?, ?, ?, 0, ?)",
                    (shift_id, prod_id, qty, qty)
                )
        return shift_id

    def sell_item(self, shift_id, product_id, qty=1):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT current_qty FROM inventory WHERE id = ?", (product_id,))
            res = cursor.fetchone()
            if not res or res[0] < qty:
                return False, "Недостаточно товара на складе!"

            cursor.execute("UPDATE inventory SET current_qty = current_qty - ? WHERE id = ?", (qty, product_id))
            cursor.execute("""
                UPDATE shift_details 
                SET sold_qty = sold_qty + ?, final_qty = final_qty - ? 
                WHERE shift_id = ? AND product_id = ?
            """, (qty, qty, shift_id, product_id))
            return True, "Успешно"

    def close_shift(self, shift_id):
        with self.conn:
            self.conn.execute("UPDATE shifts SET is_active = 0, end_time = ? WHERE id = ?", 
                              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), shift_id))

    def get_shift_summary(self, shift_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT i.sku, i.name, sd.initial_qty, sd.sold_qty, sd.final_qty, (sd.sold_qty * i.price) as revenue
            FROM shift_details sd
            JOIN inventory i ON i.id = sd.product_id
            WHERE sd.shift_id = ?
        """, (shift_id,))
        return cursor.fetchall()

    def get_all_inventory(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, sku, name, category, price, current_qty FROM inventory")
        return cursor.fetchall()


class AutoShopApp:
    """Пользовательский интерфейс (Tkinter)"""
    def __init__(self, root):
        self.root = root
        self.root.title("АРМ Автомагазина — Учет остатков и расхода за смену")
        self.root.geometry("860x540")
        self.db = AutoShopDB()
        self.current_shift = self.db.get_active_shift()

        self.setup_ui()
        self.refresh_table()

    def setup_ui(self):
        # Верхняя панель управления сменой
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        self.shift_label = ttk.Label(top_frame, text="", font=("Arial", 11, "bold"))
        self.shift_label.pack(side=tk.LEFT)

        self.btn_shift = ttk.Button(top_frame, command=self.toggle_shift)
        self.btn_shift.pack(side=tk.RIGHT)
        self.update_shift_ui()

        # Таблица остатков товаров
        table_frame = ttk.Frame(self.root, padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "sku", "name", "category", "price", "qty")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=12)
        self.tree.heading("id", text="ID")
        self.tree.heading("sku", text="Артикул")
        self.tree.heading("name", text="Наименование")
        self.tree.heading("category", text="Категория")
        self.tree.heading("price", text="Цена (руб.)")
        self.tree.heading("qty", text="Остаток (поштучно)")

        self.tree.column("id", width=40, anchor=tk.CENTER)
        self.tree.column("sku", width=90, anchor=tk.CENTER)
        self.tree.column("name", width=280)
        self.tree.column("category", width=140)
        self.tree.column("price", width=90, anchor=tk.E)
        self.tree.column("qty", width=120, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Нижняя панель действий
        bottom_frame = ttk.Frame(self.root, padding=10)
        bottom_frame.pack(fill=tk.X)

        ttk.Button(bottom_frame, text="Продать выбранный товар (-1 шт.)", command=self.handle_sale).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="Обновить таблицу", command=self.refresh_table).pack(side=tk.LEFT, padx=5)

    def update_shift_ui(self):
        if self.current_shift:
            self.shift_label.config(text=f"Смена активна (ID: {self.current_shift[0]}, Начало: {self.current_shift[1]})", foreground="green")
            self.btn_shift.config(text="Завершить смену и вывести расход")
        else:
            self.shift_label.config(text="Смена закрыта. Откройте смену для учета расхода.", foreground="red")
            self.btn_shift.config(text="Открыть новую смену")

    def toggle_shift(self):
        if self.current_shift:
            shift_id = self.current_shift[0]
            summary = self.db.get_shift_summary(shift_id)
            self.db.close_shift(shift_id)
            self.current_shift = None
            self.update_shift_ui()
            self.show_summary_window(summary)
        else:
            shift_id = self.db.open_shift()
            self.current_shift = self.db.get_active_shift()
            self.update_shift_ui()
            messagebox.showinfo("Смена открыта", f"Смена #{shift_id} успешно запущена. Текущие остатки зафиксированы.")

    def handle_sale(self):
        if not self.current_shift:
            messagebox.showwarning("Внимание", "Нельзя списать товар при закрытой смене! Сначала откройте смену.")
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите товар из таблицы!")
            return

        item_values = self.tree.item(selected[0])["values"]
        product_id = item_values[0]

        success, msg = self.db.sell_item(self.current_shift[0], product_id, 1)
        if success:
            self.refresh_table()
        else:
            messagebox.showerror("Ошибка", msg)

    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for item in self.db.get_all_inventory():
            self.tree.insert("", tk.END, values=item)

    def show_summary_window(self, summary_data):
        """Окно итогового отчета о расходе за смену"""
        win = tk.Toplevel(self.root)
        win.title("Итоги смены — Расход товаров")
        win.geometry("750x400")

        ttk.Label(win, text="Отчет по расходу товаров за смену", font=("Arial", 12, "bold"), padding=10).pack()

        cols = ("sku", "name", "init", "sold", "final", "rev")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        tree.heading("sku", text="Артикул")
        tree.heading("name", text="Наименование")
        tree.heading("init", text="Было (нач.)")
        tree.heading("sold", text="Расход (продано)")
        tree.heading("final", text="Осталось (кон.)")
        tree.heading("rev", text="Выручка (руб.)")

        tree.column("sku", width=90, anchor=tk.CENTER)
        tree.column("name", width=250)
        tree.column("init", width=90, anchor=tk.CENTER)
        tree.column("sold", width=110, anchor=tk.CENTER)
        tree.column("final", width=90, anchor=tk.CENTER)
        tree.column("rev", width=90, anchor=tk.E)

        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        total_sold = 0
        total_rev = 0.0
        for row in summary_data:
            tree.insert("", tk.END, values=row)
            total_sold += row[3]
            total_rev += row[5]

        info = f"Всего израсходовано/продано единиц: {total_sold} шт. | Общая выручка: {total_rev:,.2f} руб."
        ttk.Label(win, text=info, font=("Arial", 10, "bold"), padding=10).pack()

if __name__ == "__main__":
    app_root = tk.Tk()
    app = AutoShopApp(app_root)
    app_root.mainloop()