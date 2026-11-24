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
                ("SKU-000001", "Масло моторное 5W-40 4L", "Масла", 2500.0, 5),
                ("SKU-000002", "Фильтр масляный W712", "Фильтры", 450.0, 10),
                ("SKU-000003", "Колодки тормозные передние", "Тормозная система", 1800.0, 3),
                ("SKU-000004", "Свеча зажигания Nickel", "Зажигание", 350.0, 16),
                ("SKU-000005", "Антифриз G12+ 5L", "Охлаждение", 1200.0, 4),
                ("SKU-000006", "Бампер передний грунтованный", "Кузов", 6500.0, 2)
            ]
            self.conn.executemany(
                "INSERT INTO inventory (sku, name, category, price, current_qty) VALUES (?, ?, ?, ?, ?)",
                sample
            )
            self.conn.commit()

    def get_next_sku(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(id) FROM inventory")
        row = cursor.fetchone()
        next_id = (row[0] or 0) + 1
        return f"SKU-{next_id:06d}"

    def get_categories(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT category FROM inventory WHERE category IS NOT NULL AND category != '' ORDER BY category")
        return [row[0] for row in cursor.fetchall()]

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

    def add_product(self, name, category, price, qty, shift_id=None):
        sku = self.get_next_sku()
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO inventory (sku, name, category, price, current_qty) VALUES (?, ?, ?, ?, ?)",
                (sku, name, category, price, qty)
            )
            prod_id = cursor.lastrowid

            if shift_id:
                cursor.execute("""
                    INSERT INTO shift_details (shift_id, product_id, initial_qty, delivered_qty, sold_qty, final_qty)
                    VALUES (?, ?, 0, ?, 0, ?)
                """, (shift_id, prod_id, qty, qty))
        return sku

    def sell_item(self, shift_id, product_id, qty=1):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT current_qty FROM inventory WHERE id = ?", (product_id,))
            res = cursor.fetchone()
            if not res:
                return False, "Товар не найден."
            if res[0] < qty:
                return False, f"Недостаточно товара на складе! В наличии всего {res[0]} шт."

            cursor.execute("UPDATE inventory SET current_qty = current_qty - ? WHERE id = ?", (qty, product_id))
            cursor.execute("""
                UPDATE shift_details 
                SET sold_qty = sold_qty + ?, final_qty = final_qty - ? 
                WHERE shift_id = ? AND product_id = ?
            """, (qty, qty, shift_id, product_id))
            return True, "Успешно"

    def delete_multiple_items(self, product_ids):
        with self.conn:
            placeholders = ",".join("?" * len(product_ids))
            self.conn.execute(f"DELETE FROM shift_details WHERE product_id IN ({placeholders})", product_ids)
            self.conn.execute(f"DELETE FROM inventory WHERE id IN ({placeholders})", product_ids)

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

    def get_inventory_filtered(self, search_query="", category_filter="Все"):
        cursor = self.conn.cursor()
        sql = "SELECT id, sku, name, category, price, current_qty FROM inventory WHERE 1=1"
        params = []

        if category_filter and category_filter != "Все":
            sql += " AND category = ?"
            params.append(category_filter)

        if search_query:
            sql += " AND (LOWER(name) LIKE ? OR LOWER(sku) LIKE ?)"
            q = f"%{search_query.lower()}%"
            params.extend([q, q])

        sql += " ORDER BY id ASC"
        cursor.execute(sql, params)
        return cursor.fetchall()


class AutoShopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("АРМ Автомагазина — Учет поштучных остатков и расхода")
        self.root.geometry("980x620")
        self.db = AutoShopDB()
        self.current_shift = self.db.get_active_shift()

        self.setup_menu()
        self.setup_ui()
        self.refresh_categories_dropdown()
        self.refresh_table()

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        self.shift_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Управление сменой", menu=self.shift_menu)
        self.update_menu_items()

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Инфо", menu=help_menu)
        help_menu.add_command(label="О системе", command=lambda: messagebox.showinfo(
            "О системе", "АРМ Автомагазина\nУчет поштучных остатков ТМЦ, расхода за смену, фильтрация и поиск."
        ))

    def update_menu_items(self):
        self.shift_menu.delete(0, tk.END)
        if self.current_shift:
            self.shift_menu.add_command(label="Завершить текущую смену...", command=self.confirm_close_shift)
        else:
            self.shift_menu.add_command(label="Открыть новую смену", command=self.open_shift_action)

    def setup_ui(self):
        # 1. Статус смены
        top_frame = ttk.Frame(self.root, padding=(12, 6))
        top_frame.pack(fill=tk.X)

        self.status_label = ttk.Label(top_frame, text="", font=("Arial", 11, "bold"))
        self.status_label.pack(side=tk.LEFT)
        self.update_status_display()

        # 2. Панель поиска и фильтрации
        search_frame = ttk.LabelFrame(self.root, text="Поиск и фильтр товаров", padding=(10, 8))
        search_frame.pack(fill=tk.X, padx=10, pady=4)

        ttk.Label(search_frame, text="Поиск по названию / SKU:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh_table())
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=28)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(search_frame, text="Категория:").pack(side=tk.LEFT, padx=(0, 5))
        self.category_var = tk.StringVar(value="Все")
        self.category_combo = ttk.Combobox(search_frame, textvariable=self.category_var, state="readonly", width=18)
        self.category_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())
        self.category_combo.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Button(search_frame, text="Сбросить фильтры", command=self.reset_filters).pack(side=tk.LEFT)

        # 3. Таблица остатков с мультивыбором
        table_frame = ttk.Frame(self.root, padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "sku", "name", "category", "price", "qty")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=14, selectmode="extended")
        self.tree.heading("id", text="ID")
        self.tree.heading("sku", text="Артикул")
        self.tree.heading("name", text="Наименование детали")
        self.tree.heading("category", text="Категория")
        self.tree.heading("price", text="Цена (руб.)")
        self.tree.heading("qty", text="В наличии (шт.)")

        self.tree.column("id", width=45, anchor=tk.CENTER)
        self.tree.column("sku", width=110, anchor=tk.CENTER)
        self.tree.column("name", width=340)
        self.tree.column("category", width=150)
        self.tree.column("price", width=110, anchor=tk.E)
        self.tree.column("qty", width=110, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 4. Панель кнопок действий
        bottom_frame = ttk.Frame(self.root, padding=10)
        bottom_frame.pack(fill=tk.X)

        ttk.Button(bottom_frame, text="🛒 Продать выбранный товар...", 
                   command=self.open_sale_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="+ Поставка / Новый товар", 
                   command=self.open_add_product_window).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="🗑 Удалить выбранные (мультивыбор)", 
                   command=self.handle_delete_multiple).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="Обновить список", 
                   command=self.refresh_table).pack(side=tk.RIGHT, padx=5)

    def reset_filters(self):
        self.search_var.set("")
        self.category_var.set("Все")
        self.refresh_table()

    def refresh_categories_dropdown(self):
        cats = ["Все"] + self.db.get_categories()
        self.category_combo["values"] = cats
        if self.category_var.get() not in cats:
            self.category_var.set("Все")

    def update_status_display(self):
        if self.current_shift:
            self.status_label.config(
                text=f"● Смена открыта (ID #{self.current_shift[0]} от {self.current_shift[1]})", 
                foreground="#008000"
            )
        else:
            self.status_label.config(
                text="○ Смена закрыта. Для продаж откройте смену через 'Управление сменой'.", 
                foreground="#B22222"
            )

    def open_shift_action(self):
        shift_id = self.db.open_shift()
        self.current_shift = self.db.get_active_shift()
        self.update_status_display()
        self.update_menu_items()
        messagebox.showinfo("Смена открыта", f"Смена #{shift_id} успешно начата.\nВсе остатки зафиксированы.")

    def confirm_close_shift(self):
        confirm = messagebox.askyesno(
            "Подтверждение закрытия смены",
            "Вы действительно хотите завершить текущую смену?\n\n"
            "Будет сформирован итоговый отчёт по расходу ТМЦ и выручке."
        )
        if confirm:
            shift_id = self.current_shift[0]
            summary = self.db.get_shift_summary(shift_id)
            self.db.close_shift(shift_id)
            self.current_shift = None
            self.update_status_display()
            self.update_menu_items()
            self.show_summary_window(summary)

    def open_sale_dialog(self):
        """Окно оформления продажи с предустановленным количеством 1"""
        if not self.current_shift:
            messagebox.showwarning("Смена закрыта", "Для оформления продаж необходимо открыть смену через верхнее меню!")
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Выбор товара", "Пожалуйста, выделите товар для продажи в таблице.")
            return

        item_values = self.tree.item(selected[0])["values"]
        prod_id = item_values[0]
        sku = item_values[1]
        prod_name = item_values[2]
        price = item_values[4]
        current_stock = item_values[5]

        # Диалог продажи
        dialog = tk.Toplevel(self.root)
        dialog.title("Оформление продажи")
        dialog.geometry("360x220")
        dialog.resizable(False, False)
        dialog.grab_set()

        ttk.Label(dialog, text=f"Товар: {prod_name}", font=("Arial", 10, "bold"), wraplength=340).pack(pady=(12, 4))
        ttk.Label(dialog, text=f"Артикул: {sku} | В наличии: {current_stock} шт. | Цена: {price} руб.").pack(pady=(0, 10))

        input_frame = ttk.Frame(dialog)
        input_frame.pack(pady=5)
        ttk.Label(input_frame, text="Количество к списанию:").pack(side=tk.LEFT, padx=5)

        # Значение 1 выставлено изначально
        qty_spinbox = ttk.Spinbox(input_frame, from_=1, to=max(1, current_stock), width=8)
        qty_spinbox.set("1")
        qty_spinbox.pack(side=tk.LEFT, padx=5)
        qty_spinbox.focus_set()
        qty_spinbox.selection_range(0, tk.END)

        def do_sale():
            try:
                qty = int(qty_spinbox.get())
                if qty <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Ошибка", "Введите корректное целое положительное число!", parent=dialog)
                return

            if qty > current_stock:
                messagebox.showerror("Недостаточно на складе", f"Нельзя списать {qty} шт. Доступно только {current_stock} шт.", parent=dialog)
                return

            success, msg = self.db.sell_item(self.current_shift[0], prod_id, qty)
            if success:
                dialog.destroy()
                self.refresh_table()
            else:
                messagebox.showerror("Ошибка списания", msg, parent=dialog)

        dialog.bind("<Return>", lambda e: do_sale())

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="Подтвердить продажу", command=do_sale).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def handle_delete_multiple(self):
        """Удаление сразу нескольких выделенных товаров"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Выбор товаров", "Выделите один или несколько товаров (зажав Ctrl или Shift).")
            return

        confirm = messagebox.askyesno(
            "Подтверждение удаления",
            f"Вы точно хотите удалить выбранные позиции ({len(selected)} шт.) со склада?\n"
            "Это действие удалит товары и связанные записи в смене."
        )
        if not confirm:
            return

        prod_ids = [self.tree.item(item_id)["values"][0] for item_id in selected]
        self.db.delete_multiple_items(prod_ids)
        self.refresh_categories_dropdown()
        self.refresh_table()
        messagebox.showinfo("Успешно", f"Удалено позиций: {len(prod_ids)}")

    def open_add_product_window(self):
        """Окно прихода товара (артикул генерируется автоматически)"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Поставка / Добавление товара")
        dialog.geometry("400x260")
        dialog.resizable(False, False)
        dialog.grab_set()

        next_sku = self.db.get_next_sku()

        ttk.Label(dialog, text="Артикул (авто):").grid(row=0, column=0, padx=10, pady=8, sticky=tk.W)
        sku_info = ttk.Label(dialog, text=f"{next_sku} (присвоится автоматически)", foreground="gray")
        sku_info.grid(row=0, column=1, padx=10, pady=8, sticky=tk.W)

        ttk.Label(dialog, text="Наименование:").grid(row=1, column=0, padx=10, pady=8, sticky=tk.W)
        entry_name = ttk.Entry(dialog, width=28)
        entry_name.grid(row=1, column=1, padx=10, pady=8)
        entry_name.focus_set()

        ttk.Label(dialog, text="Категория:").grid(row=2, column=0, padx=10, pady=8, sticky=tk.W)
        entry_category = ttk.Entry(dialog, width=28)
        entry_category.grid(row=2, column=1, padx=10, pady=8)

        ttk.Label(dialog, text="Стоимость (руб.):").grid(row=3, column=0, padx=10, pady=8, sticky=tk.W)
        entry_price = ttk.Entry(dialog, width=28)
        entry_price.grid(row=3, column=1, padx=10, pady=8)

        ttk.Label(dialog, text="Количество (шт.):").grid(row=4, column=0, padx=10, pady=8, sticky=tk.W)
        entry_qty = ttk.Entry(dialog, width=28)
        entry_qty.grid(row=4, column=1, padx=10, pady=8)

        def save_product():
            name = entry_name.get().strip()
            category = entry_category.get().strip() or "Общая"

            if not name:
                messagebox.showerror("Ошибка", "Наименование детали обязательно к заполнению!", parent=dialog)
                return

            try:
                price = float(entry_price.get().replace(",", "."))
                qty = int(entry_qty.get())
                if price < 0 or qty <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Ошибка", "Цена должна быть числом >= 0, а количество — положительным целым!", parent=dialog)
                return

            shift_id = self.current_shift[0] if self.current_shift else None
            assigned_sku = self.db.add_product(name, category, price, qty, shift_id)
            
            self.refresh_categories_dropdown()
            self.refresh_table()
            dialog.destroy()
            messagebox.showinfo("Успешно", f"Товар '{name}' успешно добавлен!\nПрисвоен артикул: {assigned_sku}")

        ttk.Button(dialog, text="Принять на склад", command=save_product).grid(row=5, column=0, columnspan=2, pady=16)

    def refresh_table(self):
        """Обновление таблицы с учётом фильтра и строки поиска"""
        query = self.search_var.get().strip()
        cat = self.category_var.get()

        for row in self.tree.get_children():
            self.tree.delete(row)

        items = self.db.get_inventory_filtered(query, cat)
        inserted_items = []
        for item in items:
            node = self.tree.insert("", tk.END, values=item)
            inserted_items.append(node)

        # Если поиск дал конкретный результат (1 товар), автоматически выделяем его для удобства
        if query and len(inserted_items) == 1:
            self.tree.selection_set(inserted_items[0])
            self.tree.focus(inserted_items[0])

    def show_summary_window(self, summary_data):
        """Окно итоговой ведомости расхода ТМЦ за смену"""
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

        tree.column("sku", width=90, anchor=tk.CENTER)
        tree.column("name", width=230)
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

        info = f"Всего списано (продано) деталей: {total_sold} шт. | Общая выручка: {total_rev:,.2f} руб."
        ttk.Label(win, text=info, font=("Arial", 10, "bold"), padding=10).pack()


if __name__ == "__main__":
    app_root = tk.Tk()
    app = AutoShopApp(app_root)
    app_root.mainloop()