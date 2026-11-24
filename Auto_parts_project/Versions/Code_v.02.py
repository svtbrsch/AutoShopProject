import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

class AutoShopDB:
    """Слой работы с базой данных (SQLite)"""
    def __init__(self, db_name="autoshop.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        with self.conn:
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
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TEXT,
                    end_time TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS shift_details (
                    shift_id INTEGER,
                    product_id INTEGER,
                    initial_qty INTEGER,
                    delivered_qty INTEGER DEFAULT 0,
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
            cursor.execute("INSERT INTO shifts (start_time, is_active) VALUES (?, 1)", 
                           (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
            shift_id = cursor.lastrowid
            
            cursor.execute("SELECT id, current_qty FROM inventory")
            items = cursor.fetchall()
            for prod_id, qty in items:
                cursor.execute(
                    "INSERT INTO shift_details (shift_id, product_id, initial_qty, delivered_qty, sold_qty, final_qty) VALUES (?, ?, ?, 0, 0, ?)",
                    (shift_id, prod_id, qty, qty)
                )
        return shift_id

    def add_or_update_product(self, sku, name, category, price, qty, shift_id=None):
        """Добавление нового товара или поставка существующего"""
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, current_qty FROM inventory WHERE sku = ?", (sku,))
            existing = cursor.fetchone()

            if existing:
                prod_id, old_qty = existing
                cursor.execute("UPDATE inventory SET current_qty = current_qty + ?, price = ?, name = ?, category = ? WHERE id = ?",
                               (qty, price, name, category, prod_id))
            else:
                cursor.execute("INSERT INTO inventory (sku, name, category, price, current_qty) VALUES (?, ?, ?, ?, ?)",
                               (sku, name, category, price, qty))
                prod_id = cursor.lastrowid

            # Если смена активна, обновляем данные в смене
            if shift_id:
                cursor.execute("SELECT initial_qty, delivered_qty, sold_qty, final_qty FROM shift_details WHERE shift_id = ? AND product_id = ?",
                               (shift_id, prod_id))
                detail = cursor.fetchone()
                if detail:
                    cursor.execute("""
                        UPDATE shift_details 
                        SET delivered_qty = delivered_qty + ?, final_qty = final_qty + ? 
                        WHERE shift_id = ? AND product_id = ?
                    """, (qty, qty, shift_id, prod_id))
                else:
                    cursor.execute("""
                        INSERT INTO shift_details (shift_id, product_id, initial_qty, delivered_qty, sold_qty, final_qty)
                        VALUES (?, ?, 0, ?, 0, ?)
                    """, (shift_id, prod_id, qty, qty))
        return True

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
            SELECT i.sku, i.name, sd.initial_qty, sd.delivered_qty, sd.sold_qty, sd.final_qty, (sd.sold_qty * i.price) as revenue
            FROM shift_details sd
            JOIN inventory i ON i.id = sd.product_id
            WHERE sd.shift_id = ?
        """, (shift_id,))
        return cursor.fetchall()

    def get_all_inventory(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, sku, name, category, price, current_qty FROM inventory ORDER BY id ASC")
        return cursor.fetchall()


class AutoShopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("АРМ Автомагазина — Учет поштучных остатков и расхода")
        self.root.geometry("920x560")
        self.db = AutoShopDB()
        self.current_shift = self.db.get_active_shift()

        self.setup_menu()
        self.setup_ui()
        self.refresh_table()

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Выпадающее меню "Смена"
        self.shift_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Управление сменой", menu=self.shift_menu)
        self.update_menu_items()

        # Меню "Справка"
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Инфо", menu=help_menu)
        help_menu.add_command(label="О системе", command=lambda: messagebox.showinfo(
            "О системе", "АРМ Автомагазина\nАрхитектура: Python + SQLite + Tkinter\nУчёт ТМЦ поштучно за смену."
        ))

    def update_menu_items(self):
        self.shift_menu.delete(0, tk.END)
        if self.current_shift:
            self.shift_menu.add_command(label="Завершить текущую смену", command=self.confirm_close_shift)
        else:
            self.shift_menu.add_command(label="Открыть новую смену", command=self.open_shift_action)

    def setup_ui(self):
        # Информационная плашка статуса смены
        top_frame = ttk.Frame(self.root, padding=(10, 8))
        top_frame.pack(fill=tk.X)

        self.status_label = ttk.Label(top_frame, text="", font=("Arial", 11, "bold"))
        self.status_label.pack(side=tk.LEFT)
        self.update_status_display()

        # Таблица остатков
        table_frame = ttk.Frame(self.root, padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "sku", "name", "category", "price", "qty")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=14)
        self.tree.heading("id", text="ID")
        self.tree.heading("sku", text="Артикул")
        self.tree.heading("name", text="Наименование детали")
        self.tree.heading("category", text="Категория")
        self.tree.heading("price", text="Цена (руб.)")
        self.tree.heading("qty", text="В наличии (шт.)")

        self.tree.column("id", width=45, anchor=tk.CENTER)
        self.tree.column("sku", width=100, anchor=tk.CENTER)
        self.tree.column("name", width=300)
        self.tree.column("category", width=140)
        self.tree.column("price", width=100, anchor=tk.E)
        self.tree.column("qty", width=110, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Панель быстрых действий
        bottom_frame = ttk.Frame(self.root, padding=10)
        bottom_frame.pack(fill=tk.X)

        ttk.Button(bottom_frame, text="Списать / Продать выбранное (-1 шт.)", 
                   command=self.handle_sale).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="+ Поставка / Новый товар", 
                   command=self.open_add_product_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="Обновить список", 
                   command=self.refresh_table).pack(side=tk.RIGHT, padx=5)

    def update_status_display(self):
        if self.current_shift:
            self.status_label.config(
                text=f"● Смена открыта (ID #{self.current_shift[0]} от {self.current_shift[1]})", 
                foreground="#008000"
            )
        else:
            self.status_label.config(
                text="○ Смена закрыта. Чтобы начать продажи, откройте смену через меню.", 
                foreground="#B22222"
            )

    def open_shift_action(self):
        shift_id = self.db.open_shift()
        self.current_shift = self.db.get_active_shift()
        self.update_status_display()
        self.update_menu_items()
        messagebox.showinfo("Смена открыта", f"Смена #{shift_id} успешно начата.\nВсе начальные остатки зафиксированы.")

    def confirm_close_shift(self):
        """Диалог подтверждения перед закрытием смены"""
        confirm = messagebox.askyesno(
            "Подтверждение закрытия смены",
            "Вы уверены, что хотите завершить текущую смену?\n\n"
            "Это действие зафиксирует конечные остатки, сформирует отчёт о расходе и выручке, "
            "после чего продажи до открытия новой смены будут приостановлены."
        )
        if confirm:
            shift_id = self.current_shift[0]
            summary = self.db.get_shift_summary(shift_id)
            self.db.close_shift(shift_id)
            self.current_shift = None
            self.update_status_display()
            self.update_menu_items()
            self.show_summary_window(summary)

    def handle_sale(self):
        if not self.current_shift:
            messagebox.showwarning("Смена закрыта", "Для списания товара необходимо открыть смену через верхнее меню!")
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Выбор товара", "Пожалуйста, выделите строку с товаром в таблице.")
            return

        item_values = self.tree.item(selected[0])["values"]
        prod_id = item_values[0]

        success, msg = self.db.sell_item(self.current_shift[0], prod_id, 1)
        if success:
            self.refresh_table()
        else:
            messagebox.showerror("Ошибка списания", msg)

    def open_add_product_window(self):
        """Окно оформления поставки или добавления нового товара"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Поставка / Добавление товара")
        dialog.geometry("380x300")
        dialog.resizable(False, False)
        dialog.grab_set()  # Модальный режим

        ttk.Label(dialog, text="Артикул (SKU):").grid(row=0, column=0, padx=10, pady=8, sticky=tk.W)
        entry_sku = ttk.Entry(dialog, width=25)
        entry_sku.grid(row=0, column=1, padx=10, pady=8)

        ttk.Label(dialog, text="Наименование:").grid(row=1, column=0, padx=10, pady=8, sticky=tk.W)
        entry_name = ttk.Entry(dialog, width=25)
        entry_name.grid(row=1, column=1, padx=10, pady=8)

        ttk.Label(dialog, text="Категория:").grid(row=2, column=0, padx=10, pady=8, sticky=tk.W)
        entry_category = ttk.Entry(dialog, width=25)
        entry_category.grid(row=2, column=1, padx=10, pady=8)

        ttk.Label(dialog, text="Стоимость (руб.):").grid(row=3, column=0, padx=10, pady=8, sticky=tk.W)
        entry_price = ttk.Entry(dialog, width=25)
        entry_price.grid(row=3, column=1, padx=10, pady=8)

        ttk.Label(dialog, text="Количество (шт.):").grid(row=4, column=0, padx=10, pady=8, sticky=tk.W)
        entry_qty = ttk.Entry(dialog, width=25)
        entry_qty.grid(row=4, column=1, padx=10, pady=8)

        def save_product():
            sku = entry_sku.get().strip()
            name = entry_name.get().strip()
            category = entry_category.get().strip()
            
            if not sku or not name:
                messagebox.showerror("Ошибка", "Артикул и наименование обязательны для заполнения!", parent=dialog)
                return

            try:
                price = float(entry_price.get().replace(",", "."))
                qty = int(entry_qty.get())
                if price < 0 or qty <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Ошибка", "Стоимость должна быть числом >= 0, а количество — целым положительным числом!", parent=dialog)
                return

            shift_id = self.current_shift[0] if self.current_shift else None
            self.db.add_or_update_product(sku, name, category, price, qty, shift_id)
            self.refresh_table()
            dialog.destroy()
            messagebox.showinfo("Успешно", f"Товар '{name}' ({qty} шт.) успешно принят на склад!")

        ttk.Button(dialog, text="Принять на склад", command=save_product).grid(row=5, column=0, columnspan=2, pady=15)

    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for item in self.db.get_all_inventory():
            self.tree.insert("", tk.END, values=item)

    def show_summary_window(self, summary_data):
        """Окно итоговой ведомости расхода за смену"""
        win = tk.Toplevel(self.root)
        win.title("Итоговая ведомость — Расход за смену")
        win.geometry("820x420")

        ttk.Label(win, text="Акт расхода товаров и реализации за смену", 
                  font=("Arial", 12, "bold"), padding=10).pack()

        cols = ("sku", "name", "init", "delivered", "sold", "final", "rev")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        tree.heading("sku", text="Артикул")
        tree.heading("name", text="Наименование")
        tree.heading("init", text="Было (нач.)")
        tree.heading("delivered", text="Поставка (+)")
        tree.heading("sold", text="Расход (продано)")
        tree.heading("final", text="Остаток (кон.)")
        tree.heading("rev", text="Сумма (руб.)")

        tree.column("sku", width=85, anchor=tk.CENTER)
        tree.column("name", width=220)
        tree.column("init", width=75, anchor=tk.CENTER)
        tree.column("delivered", width=85, anchor=tk.CENTER)
        tree.column("sold", width=105, anchor=tk.CENTER)
        tree.column("final", width=85, anchor=tk.CENTER)
        tree.column("rev", width=85, anchor=tk.E)

        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        total_sold = 0
        total_rev = 0.0
        for row in summary_data:
            tree.insert("", tk.END, values=row)
            total_sold += row[4]
            total_rev += row[6]

        info = f"Всего израсходовано деталей: {total_sold} шт. | Общая сумма реализации: {total_rev:,.2f} руб."
        ttk.Label(win, text=info, font=("Arial", 10, "bold"), padding=10).pack()


if __name__ == "__main__":
    app_root = tk.Tk()
    app = AutoShopApp(app_root)
    app_root.mainloop()