import datetime
import os
import sqlite3
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk


class AutoShopDB:
    """Слой работы с базой данных (SQLite)"""

    def __init__(self, db_name="autoshop.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        with self.conn:
            # Справочник категорий
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            """
            )
            # Справочник товаров
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE,
                    name TEXT,
                    category TEXT,
                    price REAL,
                    current_qty INTEGER
                )
            """
            )
            # Журнал смен
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TEXT,
                    end_time TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """
            )
            # Движение за смену
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shift_details (
                    shift_id INTEGER,
                    product_id INTEGER,
                    initial_qty INTEGER,
                    supplied_qty INTEGER DEFAULT 0,
                    sold_qty INTEGER DEFAULT 0,
                    defect_qty INTEGER DEFAULT 0,
                    final_qty INTEGER,
                    PRIMARY KEY(shift_id, product_id)
                )
            """
            )
            # Журнал транзакций продаж за смену (для разделения нал / безнал)
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sales_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shift_id INTEGER,
                    product_id INTEGER,
                    qty INTEGER,
                    price_per_item REAL,
                    payment_type TEXT,
                    timestamp TEXT
                )
            """
            )
            # Касса наличных
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cash_box (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    balance REAL DEFAULT 0.0
                )
            """
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO cash_box (id, balance) VALUES (1, 0.0)"
            )
            self.seed_defaults()

    def seed_defaults(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM categories")
        if cursor.fetchone()[0] == 0:
            default_categories = [
                ("Фильтры",),
                ("Свечи",),
                ("Тормозная система",),
                ("Масла и жидкости",),
            ]
            cursor.executemany(
                "INSERT INTO categories (name) VALUES (?)", default_categories
            )

        cursor.execute("SELECT COUNT(*) FROM inventory")
        if cursor.fetchone()[0] == 0:
            demo_items = [
                ("AP-1001", "Масляный фильтр W712/94", "Фильтры", 650.0, 15),
                ("AP-1002", "Свеча NGK BKR6E-11", "Свечи", 350.0, 24),
                (
                    "AP-1003",
                    "Колодки тормозные Brembo P85020",
                    "Тормозная система",
                    2800.0,
                    6,
                ),
                (
                    "AP-1004",
                    "Моторное масло 5W-40 4L",
                    "Масла и жидкости",
                    3400.0,
                    10,
                ),
            ]
            cursor.executemany(
                "INSERT INTO inventory (sku, name, category, price, current_qty) VALUES (?, ?, ?, ?, ?)",
                demo_items,
            )
        self.conn.commit()

    # --- Категории ---
    def get_categories(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM categories ORDER BY name")
        return [row[0] for row in cursor.fetchall()]

    def add_category(self, name):
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO categories (name) VALUES (?)", (name,)
                )
            return True, "Категория добавлена"
        except sqlite3.IntegrityError:
            return False, "Категория уже существует"

    def delete_category(self, name):
        with self.conn:
            self.conn.execute(
                "DELETE FROM categories WHERE name = ?", (name,)
            )

    # --- Генерация артикула ---
    def generate_next_sku(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(id) FROM inventory")
        max_id = cursor.fetchone()[0] or 0
        return f"AP-{1000 + max_id + 1}"

    # --- Управление сменами ---
    def get_active_shift(self):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, start_time FROM shifts WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )
        return cursor.fetchone()

    def open_shift(self):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO shifts (start_time, is_active) VALUES (?, 1)",
                (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),),
            )
            shift_id = cursor.lastrowid

            cursor.execute("SELECT id, current_qty FROM inventory")
            items = cursor.fetchall()
            for prod_id, qty in items:
                cursor.execute(
                    """
                    INSERT INTO shift_details 
                    (shift_id, product_id, initial_qty, supplied_qty, sold_qty, defect_qty, final_qty) 
                    VALUES (?, ?, ?, 0, 0, 0, ?)
                """,
                    (shift_id, prod_id, qty, qty),
                )
        return shift_id

    def close_shift(self, shift_id):
        with self.conn:
            self.conn.execute(
                "UPDATE shifts SET is_active = 0, end_time = ? WHERE id = ?",
                (
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    shift_id,
                ),
            )

    # --- Касса ---
    def get_cash_balance(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT balance FROM cash_box WHERE id = 1")
        row = cursor.fetchone()
        return row[0] if row else 0.0

    def adjust_cash(self, amount):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT balance FROM cash_box WHERE id = 1")
            cur_bal = cursor.fetchone()[0]
            new_bal = cur_bal + amount
            if new_bal < 0:
                return False, "Недостаточно средств в кассе!"
            cursor.execute(
                "UPDATE cash_box SET balance = ? WHERE id = 1", (new_bal,)
            )
            return True, "Баланс кассы обновлён"

    # --- Товары ---
    def add_product(self, name, category, price, qty, shift_id=None):
        sku = self.generate_next_sku()
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO inventory (sku, name, category, price, current_qty) 
                VALUES (?, ?, ?, ?, ?)
            """,
                (sku, name, category, price, qty),
            )
            prod_id = cursor.lastrowid

            if shift_id:
                cursor.execute(
                    """
                    INSERT INTO shift_details 
                    (shift_id, product_id, initial_qty, supplied_qty, sold_qty, defect_qty, final_qty) 
                    VALUES (?, ?, 0, ?, 0, 0, ?)
                """,
                    (shift_id, prod_id, qty, qty),
                )
        return sku

    def update_product_field(self, product_id, field, value):
        with self.conn:
            self.conn.execute(
                f"UPDATE inventory SET {field} = ? WHERE id = ?",
                (value, product_id),
            )

    def delete_products(self, product_ids):
        with self.conn:
            cursor = self.conn.cursor()
            placeholders = ",".join("?" for _ in product_ids)
            cursor.execute(
                f"DELETE FROM inventory WHERE id IN ({placeholders})",
                product_ids,
            )
            cursor.execute(
                f"DELETE FROM shift_details WHERE product_id IN ({placeholders})",
                product_ids,
            )

    def get_inventory(self, search_text="", category="Все"):
        cursor = self.conn.cursor()
        query = (
            "SELECT id, sku, name, category, price, current_qty FROM inventory WHERE 1=1"
        )
        params = []

        if search_text:
            query += " AND (LOWER(name) LIKE ? OR LOWER(sku) LIKE ?)"
            params.extend(
                [f"%{search_text.lower()}%", f"%{search_text.lower()}%"]
            )

        if category and category != "Все":
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY id DESC"
        cursor.execute(query, params)
        return cursor.fetchall()

    # --- Списание и продажа ---
    def sell_item(self, shift_id, product_id, qty, payment_type="cash"):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT current_qty, price FROM inventory WHERE id = ?",
                (product_id,),
            )
            res = cursor.fetchone()
            if not res or res[0] < qty:
                return False, "Недостаточно товара на складе!"

            current_qty, price = res[0], res[1]
            total_sum = price * qty

            cursor.execute(
                "UPDATE inventory SET current_qty = current_qty - ? WHERE id = ?",
                (qty, product_id),
            )
            cursor.execute(
                """
                UPDATE shift_details 
                SET sold_qty = sold_qty + ?, final_qty = final_qty - ? 
                WHERE shift_id = ? AND product_id = ?
            """,
                (qty, qty, shift_id, product_id),
            )

            cursor.execute(
                """
                INSERT INTO sales_log (shift_id, product_id, qty, price_per_item, payment_type, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    shift_id,
                    product_id,
                    qty,
                    price,
                    payment_type,
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

            if payment_type == "cash":
                cursor.execute(
                    "UPDATE cash_box SET balance = balance + ? WHERE id = 1",
                    (total_sum,),
                )

            return True, "Успешно"

    def register_defect(self, shift_id, product_id, qty):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT current_qty FROM inventory WHERE id = ?", (product_id,)
            )
            res = cursor.fetchone()
            if not res or res[0] < qty:
                return False, "Недостаточно товара для списания!"

            cursor.execute(
                "UPDATE inventory SET current_qty = current_qty - ? WHERE id = ?",
                (qty, product_id),
            )
            cursor.execute(
                """
                UPDATE shift_details 
                SET defect_qty = defect_qty + ?, final_qty = final_qty - ? 
                WHERE shift_id = ? AND product_id = ?
            """,
                (qty, qty, shift_id, product_id),
            )
            return True, "Товар списан в брак"

    # --- Итоги смены ---
    def get_shift_summary(self, shift_id):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT 
                i.sku,
                i.name,
                sd.initial_qty,
                sd.supplied_qty,
                (sd.initial_qty + sd.supplied_qty) as total_initial,
                sd.sold_qty,
                sd.defect_qty,
                sd.final_qty,
                COALESCE((SELECT SUM(qty * price_per_item) FROM sales_log WHERE shift_id = sd.shift_id AND product_id = sd.product_id), 0.0) as revenue,
                i.price
            FROM shift_details sd
            JOIN inventory i ON sd.product_id = i.id
            WHERE sd.shift_id = ?
        """,
            (shift_id,),
        )
        return cursor.fetchall()

    def get_shift_payment_totals(self, shift_id):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT payment_type, SUM(qty * price_per_item) 
            FROM sales_log 
            WHERE shift_id = ? 
            GROUP BY payment_type
        """,
            (shift_id,),
        )
        totals = {"cash": 0.0, "card": 0.0}
        for p_type, amount in cursor.fetchall():
            totals[p_type] = amount or 0.0
        return totals


class AutoShopApp:
    """Главный пользовательский интерфейс"""

    def __init__(self, root):
        self.root = root
        self.root.title("АРМ Автомагазина — Учет остатков и расхода за смену")
        self.root.geometry("1060x650")

        self.db = AutoShopDB()
        self.current_shift = self.db.get_active_shift()

        self.setup_menu()
        self.setup_ui()
        self.refresh_table()

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Смена
        shift_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Смена", menu=shift_menu)
        shift_menu.add_command(
            label="Открыть смену", command=self.open_shift_action
        )
        shift_menu.add_command(
            label="Закрыть смену и получить отчет",
            command=self.close_shift_action,
        )

        # Касса
        cash_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Касса / Наличные", menu=cash_menu)
        cash_menu.add_command(
            label="Управление кассой", command=self.open_cash_box_window
        )

        # Справочники
        ref_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Справочники", menu=ref_menu)
        ref_menu.add_command(
            label="Категории товаров", command=self.open_category_manager
        )

    def setup_ui(self):
        # Верхний статус
        top_bar = ttk.Frame(self.root, padding=8)
        top_bar.pack(fill=tk.X)

        self.shift_label = ttk.Label(
            top_bar, text="", font=("Arial", 10, "bold")
        )
        self.shift_label.pack(side=tk.LEFT, padx=5)

        self.cash_badge = ttk.Label(
            top_bar, text="", font=("Arial", 10, "bold"), foreground="navy"
        )
        self.cash_badge.pack(side=tk.RIGHT, padx=10)

        # Панель фильтров и поиска
        filter_bar = ttk.LabelFrame(self.root, text="Фильтр и поиск", padding=8)
        filter_bar.pack(fill=tk.X, padx=10, pady=3)

        ttk.Label(filter_bar, text="Поиск:").pack(side=tk.LEFT, padx=3)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(
            filter_bar, textvariable=self.search_var, width=25
        )
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind(
            "<KeyRelease>", lambda e: self.refresh_table()
        )

        ttk.Label(filter_bar, text="Категория:").pack(side=tk.LEFT, padx=5)
        self.cat_filter_var = tk.StringVar(value="Все")
        self.cat_filter_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.cat_filter_var,
            state="readonly",
            width=20,
        )
        self.cat_filter_combo.pack(side=tk.LEFT, padx=5)
        self.cat_filter_combo.bind(
            "<<ComboboxSelected>>", lambda e: self.refresh_table()
        )

        ttk.Button(
            filter_bar, text="Сбросить", command=self.reset_filters
        ).pack(side=tk.LEFT, padx=10)
        ttk.Button(
            filter_bar,
            text="➕ Поставка / Новый товар",
            command=self.open_add_product_window,
        ).pack(side=tk.RIGHT, padx=5)

        self.update_category_filter_list()

        # Таблица остатков
        table_frame = ttk.LabelFrame(
            self.root, text="Текущие остатки на складе", padding=6
        )
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        cols = ("id", "sku", "name", "category", "price", "qty")
        self.tree = ttk.Treeview(
            table_frame, columns=cols, show="headings", selectmode="extended"
        )
        self.tree.heading("id", text="ID")
        self.tree.heading("sku", text="Артикул")
        self.tree.heading("name", text="Наименование")
        self.tree.heading("category", text="Категория")
        self.tree.heading("price", text="Цена (руб.)")
        self.tree.heading("qty", text="Остаток (шт.)")

        self.tree.column("id", width=45, anchor=tk.CENTER)
        self.tree.column("sku", width=110, anchor=tk.CENTER)
        self.tree.column("name", width=380)
        self.tree.column("category", width=160)
        self.tree.column("price", width=110, anchor=tk.E)
        self.tree.column("qty", width=100, anchor=tk.CENTER)

        scroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        self.tree.configure(yscroll=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Нижняя панель действий
        bottom_frame = ttk.Frame(self.root, padding=8)
        bottom_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Button(
            bottom_frame,
            text="💵 Одиночная продажа",
            command=self.handle_sale,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            bottom_frame,
            text="📦 Массовая продажа (Корзина)",
            command=self.open_bulk_sale_window,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            bottom_frame,
            text="⚠️ Списать брак / возврат",
            command=self.handle_defect,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            bottom_frame,
            text="🗑️ Удалить выбранные",
            command=self.handle_delete_products,
        ).pack(side=tk.RIGHT, padx=4)

    def update_shift_ui(self):
        cash_balance = self.db.get_cash_balance()
        self.cash_badge.config(
            text=f"Наличных в кассе: {cash_balance:,.2f} руб."
        )
        if self.current_shift:
            self.shift_label.config(
                text=f"🟢 Смена активна (ID: #{self.current_shift[0]} с {self.current_shift[1]})",
                foreground="green",
            )
        else:
            self.shift_label.config(
                text="🔴 Смена закрыта (Операции расхода недоступны. Откройте смену через меню)",
                foreground="red",
            )

    def update_category_filter_list(self):
        cats = ["Все"] + self.db.get_categories()
        self.cat_filter_combo["values"] = cats
        if self.cat_filter_var.get() not in cats:
            self.cat_filter_var.set("Все")

    def reset_filters(self):
        self.search_var.set("")
        self.cat_filter_var.set("Все")
        self.refresh_table()

    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        items = self.db.get_inventory(
            self.search_var.get(), self.cat_filter_var.get()
        )
        for item in items:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    item[0],
                    item[1],
                    item[2],
                    item[3],
                    f"{item[4]:.2f}",
                    item[5],
                ),
            )
        self.update_shift_ui()

    def open_shift_action(self):
        if self.current_shift:
            messagebox.showinfo(
                "Информация", f"Смена #{self.current_shift[0]} уже открыта!"
            )
            return
        shift_id = self.db.open_shift()
        self.current_shift = self.db.get_active_shift()
        self.update_shift_ui()
        messagebox.showinfo(
            "Успех", f"Смена #{shift_id} открыта! Остатки зафиксированы."
        )

    def close_shift_action(self):
        if not self.current_shift:
            messagebox.showwarning("Внимание", "Сейчас нет активной смены!")
            return

        shift_id = self.current_shift[0]

        confirm = messagebox.askyesno(
            "Подтверждение закрытия смены",
            f"Вы точно хотите закрыть смену #{shift_id}?\n"
            "После закрытия будет сформирован итоговый отчёт по расходу и выручке.",
            icon="warning",
        )
        if not confirm:
            return

        # 1. Получаем сводные данные смены
        summary = self.db.get_shift_summary(shift_id)
        payment_totals = self.db.get_shift_payment_totals(shift_id)

        # 2. Закрываем смену в БД
        self.db.close_shift(shift_id)

        # 3. Формируем и сохраняем файл блокнота .txt
        saved_file = self.export_shift_to_txt(shift_id, summary, payment_totals)

        # 4. Сбрасываем статус активной смены в приложении
        self.current_shift = None
        self.update_shift_ui()

        # 5. Отображаем сводное окно и сообщение об успешном экспорте
        self.show_summary_window(shift_id, summary, payment_totals)

        if saved_file:
            messagebox.showinfo(
                "Смена закрыта",
                f"Смена №{shift_id} успешно закрыта!\nОтчет сохранен в файл:\n{saved_file}",
            )

    def export_shift_to_txt(self, shift_id, summary_data, payment_totals=None):
        """Экспорт отчета о закрытии смены в текстовый блокнот (.txt)"""
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        display_date = now.strftime("%d.%m.%Y %H:%M:%S")

        filename = f"Отчет_смена_{shift_id}_{date_str}.txt"

        lines = [
            "=" * 65,
            f"          ОТЧЕТ ПО СМЕНЕ №{shift_id}",
            f"          Дата и время закрытия: {display_date}",
            "=" * 65,
            "",
            f"{'Товар':<30} | {'Кол-во':<8} | {'Цена/шт':<10} | {'Сумма':<10}",
            "-" * 65,
        ]

        total_revenue = 0.0
        total_qty = 0

        # summary_data возвращает кортежи:
        # [0]: sku, [1]: name, [2]: init, [3]: supp, [4]: total_init,
        # [5]: sold_qty, [6]: defect_qty, [7]: final_qty, [8]: revenue, [9]: price
        for row in summary_data:
            sold_qty = row[5]
            if sold_qty > 0:
                name = str(row[1])[:28]
                price = row[9]
                cost = row[8]

                total_qty += sold_qty
                total_revenue += cost

                lines.append(
                    f"{name:<30} | {sold_qty:<8} | {price:>9.2f}  | {cost:>9.2f}"
                )

        lines.append("-" * 65)
        lines.append(f"ИТОГО ПРОДАНО: {total_qty} шт.")
        lines.append(f"ОБЩАЯ ВЫРУЧКА: {total_revenue:,.2f} руб.")

        if payment_totals:
            cash = payment_totals.get("cash", 0.0)
            card = payment_totals.get("card", 0.0)
            lines.append(f"  - Наличными: {cash:,.2f} руб.")
            lines.append(f"  - Безналичными (карта): {card:,.2f} руб.")

        lines.append("=" * 65)

        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return filename
        except Exception as e:
            print(f"Ошибка при сохранении файла отчета: {e}")
            return None

    def open_cash_box_window(self):
        win = tk.Toplevel(self.root)
        win.title("Касса предприятия (Наличные)")
        win.geometry("380x250")
        win.grab_set()

        bal_label = ttk.Label(win, font=("Arial", 14, "bold"), padding=15)
        bal_label.pack()

        def update_bal_display():
            b = self.db.get_cash_balance()
            bal_label.config(text=f"В кассе: {b:,.2f} руб.")
            self.update_shift_ui()

        update_bal_display()

        btn_frame = ttk.Frame(win, padding=10)
        btn_frame.pack(fill=tk.BOTH, expand=True)

        def add_cash_action():
            val = simpledialog.askfloat(
                "Внесение наличных",
                "Введите сумму для внесения (руб.):",
                parent=win,
                minvalue=0.01,
            )
            if val:
                self.db.adjust_cash(val)
                update_bal_display()
                messagebox.showinfo(
                    "Успешно", f"Внесено: {val:,.2f} руб.", parent=win
                )

        def withdraw_cash_action():
            val = simpledialog.askfloat(
                "Изъятие наличных",
                "Введите сумму для изъятия / инкассации (руб.):",
                parent=win,
                minvalue=0.01,
            )
            if val:
                ok, res = self.db.adjust_cash(-val)
                if ok:
                    update_bal_display()
                    messagebox.showinfo(
                        "Успешно", f"Изъято: {val:,.2f} руб.", parent=win
                    )
                else:
                    messagebox.showerror("Ошибка", res, parent=win)

        ttk.Button(
            btn_frame,
            text="📥 Внести наличные (размен)",
            command=add_cash_action,
        ).pack(fill=tk.X, pady=5)
        ttk.Button(
            btn_frame,
            text="📤 Изъять наличные (инкассация)",
            command=withdraw_cash_action,
        ).pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text="Закрыть", command=win.destroy).pack(
            fill=tk.X, pady=10
        )

    def handle_sale(self):
        if not self.current_shift:
            messagebox.showwarning(
                "Внимание",
                "Нельзя списать товар при закрытой смене! Сначала откройте смену.",
            )
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите товар для продажи!")
            return

        item = self.tree.item(selected[0])["values"]
        prod_id, prod_name, max_qty, price = (
            item[0],
            item[2],
            item[5],
            float(item[4]),
        )

        sale_win = tk.Toplevel(self.root)
        sale_win.title("Оформление продажи")
        sale_win.geometry("380x280")
        sale_win.grab_set()

        ttk.Label(
            sale_win,
            text=f"Товар: {prod_name}",
            font=("Arial", 10, "bold"),
            wraplength=350,
        ).pack(pady=8)
        ttk.Label(sale_win, text=f"Доступно: {max_qty} шт. | Цена: {price:.2f} руб.").pack()

        form = ttk.Frame(sale_win, padding=10)
        form.pack()

        ttk.Label(form, text="Количество:").grid(row=0, column=0, sticky=tk.W, pady=5)
        qty_spin = ttk.Spinbox(form, from_=1, to=max_qty, width=10)
        qty_spin.set(1)
        qty_spin.grid(row=0, column=1, pady=5)

        ttk.Label(form, text="Способ оплаты:").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        pay_type_var = tk.StringVar(value="cash")
        pay_combo = ttk.Combobox(
            form,
            textvariable=pay_type_var,
            values=["cash", "card"],
            state="readonly",
            width=10,
        )
        pay_combo.grid(row=1, column=1, pady=5)

        total_lbl = ttk.Label(
            sale_win,
            text=f"Итого к оплате: {price:,.2f} руб.",
            font=("Arial", 11, "bold"),
        )
        total_lbl.pack(pady=5)

        def update_total(*args):
            try:
                q = int(qty_spin.get())
                total_lbl.config(text=f"Итого к оплате: {q * price:,.2f} руб.")
            except ValueError:
                pass

        qty_spin.bind("<KeyRelease>", update_total)
        qty_spin.bind("<<Increment>>", update_total)
        qty_spin.bind("<<Decrement>>", update_total)

        def confirm_sale():
            try:
                qty = int(qty_spin.get())
                if qty <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Ошибка", "Введите корректное число!", parent=sale_win
                )
                return

            pay_type = pay_type_var.get()
            ok, msg = self.db.sell_item(
                self.current_shift[0], prod_id, qty, payment_type=pay_type
            )
            if ok:
                sale_win.destroy()
                self.refresh_table()
            else:
                messagebox.showerror("Ошибка", msg, parent=sale_win)

        btn_box = ttk.Frame(sale_win, padding=10)
        btn_box.pack()
        ttk.Button(
            btn_box, text="Подтвердить продажу", command=confirm_sale
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_box, text="Отмена", command=sale_win.destroy).pack(
            side=tk.LEFT, padx=5
        )

    def open_bulk_sale_window(self):
        if not self.current_shift:
            messagebox.showwarning(
                "Внимание",
                "Нельзя списать товар при закрытой смене! Сначала откройте смену.",
            )
            return

        win = tk.Toplevel(self.root)
        win.title("Массовая продажа товаров (Корзина)")
        win.geometry("820x520")
        win.grab_set()

        cart = {}

        panes = ttk.PanedWindow(win, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left_frame = ttk.LabelFrame(panes, text="Каталог товаров", padding=5)
        panes.add(left_frame, weight=1)

        left_tree = ttk.Treeview(
            left_frame,
            columns=("id", "name", "price", "qty"),
            show="headings",
            height=15,
        )
        left_tree.heading("id", text="ID")
        left_tree.heading("name", text="Товар")
        left_tree.heading("price", text="Цена")
        left_tree.heading("qty", text="Остаток")

        left_tree.column("id", width=35, anchor=tk.CENTER)
        left_tree.column("name", width=180)
        left_tree.column("price", width=70, anchor=tk.E)
        left_tree.column("qty", width=60, anchor=tk.CENTER)
        left_tree.pack(fill=tk.BOTH, expand=True)

        for row in self.db.get_inventory():
            left_tree.insert(
                "",
                tk.END,
                values=(row[0], row[2], f"{row[4]:.2f}", row[5]),
            )

        right_frame = ttk.LabelFrame(panes, text="Корзина (чек)", padding=5)
        panes.add(right_frame, weight=1)

        cart_tree = ttk.Treeview(
            right_frame,
            columns=("id", "name", "qty", "price", "sum"),
            show="headings",
            height=15,
        )
        cart_tree.heading("id", text="ID")
        cart_tree.heading("name", text="Товар")
        cart_tree.heading("qty", text="Кол-во")
        cart_tree.heading("price", text="Цена")
        cart_tree.heading("sum", text="Сумма")

        cart_tree.column("id", width=30, anchor=tk.CENTER)
        cart_tree.column("name", width=150)
        cart_tree.column("qty", width=55, anchor=tk.CENTER)
        cart_tree.column("price", width=65, anchor=tk.E)
        cart_tree.column("sum", width=75, anchor=tk.E)
        cart_tree.pack(fill=tk.BOTH, expand=True)

        lbl_cart_total = ttk.Label(
            right_frame,
            text="Итого: 0.00 руб.",
            font=("Arial", 11, "bold"),
            padding=5,
        )
        lbl_cart_total.pack()

        def update_cart_display():
            for item in cart_tree.get_children():
                cart_tree.delete(item)
            total = 0.0
            for pid, data in cart.items():
                s = data["qty"] * data["price"]
                total += s
                cart_tree.insert(
                    "",
                    tk.END,
                    values=(
                        pid,
                        data["name"],
                        data["qty"],
                        f"{data['price']:.2f}",
                        f"{s:.2f}",
                    ),
                )
            lbl_cart_total.config(text=f"Итого: {total:,.2f} руб.")

        def add_to_cart():
            sel = left_tree.selection()
            if not sel:
                return
            item = left_tree.item(sel[0])["values"]
            pid, name, price, stock = (
                item[0],
                item[1],
                float(item[2]),
                int(item[3]),
            )

            current_in_cart = cart.get(pid, {}).get("qty", 0)
            if current_in_cart + 1 > stock:
                messagebox.showwarning(
                    "Внимание",
                    "На складе нет такого количества товара!",
                    parent=win,
                )
                return

            if pid in cart:
                cart[pid]["qty"] += 1
            else:
                cart[pid] = {
                    "name": name,
                    "price": price,
                    "qty": 1,
                    "max_qty": stock,
                }
            update_cart_display()

        def remove_from_cart():
            sel = cart_tree.selection()
            if not sel:
                return
            pid = cart_tree.item(sel[0])["values"][0]
            if pid in cart:
                if cart[pid]["qty"] > 1:
                    cart[pid]["qty"] -= 1
                else:
                    del cart[pid]
            update_cart_display()

        ttk.Button(
            left_frame, text="➕ Добавить в чек (+1)", command=add_to_cart
        ).pack(pady=5)
        ttk.Button(
            right_frame, text="➖ Убавить из чека (-1)", command=remove_from_cart
        ).pack(pady=5)

        bottom_cart = ttk.Frame(win, padding=10)
        bottom_cart.pack(fill=tk.X)

        ttk.Label(bottom_cart, text="Способ оплаты чека:").pack(
            side=tk.LEFT, padx=5
        )
        bulk_pay_type = tk.StringVar(value="cash")
        ttk.Combobox(
            bottom_cart,
            textvariable=bulk_pay_type,
            values=["cash", "card"],
            state="readonly",
            width=10,
        ).pack(side=tk.LEFT, padx=5)

        def complete_bulk_sale():
            if not cart:
                messagebox.showwarning(
                    "Внимание", "Корзина пуста!", parent=win
                )
                return

            pay_method = bulk_pay_type.get()
            for pid, data in cart.items():
                ok, msg = self.db.sell_item(
                    self.current_shift[0],
                    pid,
                    data["qty"],
                    payment_type=pay_method,
                )
                if not ok:
                    messagebox.showerror(
                        "Ошибка при оформлении",
                        f"{data['name']}: {msg}",
                        parent=win,
                    )
                    self.refresh_table()
                    win.destroy()
                    return

            messagebox.showinfo("Успех", "Чек успешно проведён!", parent=win)
            self.refresh_table()
            win.destroy()

        ttk.Button(
            bottom_cart, text="✅ Пробить чек", command=complete_bulk_sale
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bottom_cart, text="Отмена", command=win.destroy).pack(
            side=tk.RIGHT, padx=5
        )

    def handle_defect(self):
        if not self.current_shift:
            messagebox.showwarning(
                "Внимание",
                "Нельзя списать товар при закрытой смене! Сначала откройте смену.",
            )
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning(
                "Внимание", "Выберите товар для списания в брак!"
            )
            return

        item = self.tree.item(selected[0])["values"]
        prod_id, prod_name, max_qty = item[0], item[2], item[5]

        qty = simpledialog.askinteger(
            "Списание брака/возврата",
            f"Товар: {prod_name}\nДоступно на складе: {max_qty} шт.\n\nВведите списываемое количество:",
            initialvalue=1,
            minvalue=1,
            maxvalue=max_qty,
            parent=self.root,
        )
        if qty:
            ok, msg = self.db.register_defect(
                self.current_shift[0], prod_id, qty
            )
            if ok:
                messagebox.showinfo("Успешно", f"Списано {qty} шт. брака.")
                self.refresh_table()
            else:
                messagebox.showerror("Ошибка", msg)

    def open_add_product_window(self):
        cats = self.db.get_categories()
        if not cats:
            messagebox.showwarning(
                "Внимание",
                "Сначала создайте хотя бы одну категорию через 'Справочники'!",
            )
            return

        win = tk.Toplevel(self.root)
        win.title("Поставка / Новый товар")
        win.geometry("400x290")
        win.grab_set()

        next_sku = self.db.generate_next_sku()
        form = ttk.Frame(win, padding=15)
        form.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            form, text=f"Артикул (авто): {next_sku}", font=("Arial", 10, "bold")
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=5)

        ttk.Label(form, text="Наименование:").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        name_entry = ttk.Entry(form, width=28)
        name_entry.grid(row=1, column=1, pady=5)
        name_entry.focus()

        ttk.Label(form, text="Категория:").grid(
            row=2, column=0, sticky=tk.W, pady=5
        )
        cat_combo = ttk.Combobox(form, values=cats, state="readonly", width=26)
        cat_combo.set(cats[0])
        cat_combo.grid(row=2, column=1, pady=5)

        ttk.Label(form, text="Цена (руб.):").grid(
            row=3, column=0, sticky=tk.W, pady=5
        )
        price_entry = ttk.Entry(form, width=28)
        price_entry.grid(row=3, column=1, pady=5)

        ttk.Label(form, text="Количество (шт.):").grid(
            row=4, column=0, sticky=tk.W, pady=5
        )
        qty_entry = ttk.Entry(form, width=28)
        qty_entry.grid(row=4, column=1, pady=5)

        def save_product():
            name = name_entry.get().strip()
            cat = cat_combo.get()
            try:
                price = float(price_entry.get())
                qty = int(qty_entry.get())
                if price <= 0 or qty < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "Ошибка",
                    "Укажите корректную положительную цену и количество!",
                    parent=win,
                )
                return

            if not name:
                messagebox.showerror(
                    "Ошибка", "Наименование не может быть пустым!", parent=win
                )
                return

            shift_id = self.current_shift[0] if self.current_shift else None
            self.db.add_product(name, cat, price, qty, shift_id=shift_id)
            self.refresh_table()
            win.destroy()
            messagebox.showinfo("Успех", f"Товар '{name}' успешно оприходован!")

        ttk.Button(form, text="Оприходовать товар", command=save_product).grid(
            row=5, column=0, columnspan=2, pady=15
        )

    def handle_delete_products(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning(
                "Внимание", "Выберите хотя бы один товар для удаления!"
            )
            return

        cnt = len(selected)
        confirm = messagebox.askyesno(
            "Подтверждение",
            f"Вы точно хотите удалить выбранные позиции ({cnt} шт.)?\nЭто действие нельзя отменить!",
            icon="warning",
        )
        if not confirm:
            return

        ids = [self.tree.item(item)["values"][0] for item in selected]
        self.db.delete_products(ids)
        self.refresh_table()
        messagebox.showinfo("Успешно", "Выбранные товары удалены.")

    def open_category_manager(self):
        win = tk.Toplevel(self.root)
        win.title("Управление категориями")
        win.geometry("350x380")
        win.grab_set()

        cat_list = tk.Listbox(win, height=12)
        cat_list.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        def reload_cats():
            cat_list.delete(0, tk.END)
            for c in self.db.get_categories():
                cat_list.insert(tk.END, c)
            self.update_category_filter_list()

        reload_cats()

        ctrl_frame = ttk.Frame(win, padding=5)
        ctrl_frame.pack(fill=tk.X)

        new_entry = ttk.Entry(ctrl_frame)
        new_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        def add_c():
            val = new_entry.get().strip()
            if val:
                ok, msg = self.db.add_category(val)
                if ok:
                    new_entry.delete(0, tk.END)
                    reload_cats()
                else:
                    messagebox.showerror("Ошибка", msg, parent=win)

        ttk.Button(ctrl_frame, text="Добавить", command=add_c).pack(
            side=tk.RIGHT, padx=5
        )

        def del_c():
            sel = cat_list.curselection()
            if not sel:
                return
            c_name = cat_list.get(sel[0])
            self.db.delete_category(c_name)
            reload_cats()

        ttk.Button(win, text="Удалить выбранную", command=del_c).pack(
            fill=tk.X, padx=10, pady=5
        )

    def show_summary_window(self, shift_id, summary_rows, payment_totals):
        win = tk.Toplevel(self.root)
        win.title(f"Итоговый отчет за смену #{shift_id}")
        win.geometry("980x480")

        cols = (
            "sku",
            "name",
            "initial",
            "supplied",
            "total_initial",
            "sold",
            "defect",
            "final",
            "revenue",
        )
        tree = ttk.Treeview(win, columns=cols, show="headings")
        tree.heading("sku", text="Артикул")
        tree.heading("name", text="Наименование")
        tree.heading("initial", text="Начало")
        tree.heading("supplied", text="Приход")
        tree.heading("total_initial", text="Всего")
        tree.heading("sold", text="Продано")
        tree.heading("defect", text="Брак")
        tree.heading("final", text="Остаток")
        tree.heading("revenue", text="Выручка (руб.)")

        tree.column("sku", width=85, anchor=tk.CENTER)
        tree.column("name", width=250)
        tree.column("initial", width=60, anchor=tk.CENTER)
        tree.column("supplied", width=60, anchor=tk.CENTER)
        tree.column("total_initial", width=60, anchor=tk.CENTER)
        tree.column("sold", width=60, anchor=tk.CENTER)
        tree.column("defect", width=60, anchor=tk.CENTER)
        tree.column("final", width=60, anchor=tk.CENTER)
        tree.column("revenue", width=95, anchor=tk.E)

        total_sold = 0
        total_defect = 0
        total_rev = 0.0

        for r in summary_rows:
            tree.insert(
                "",
                tk.END,
                values=(
                    r[0],
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    r[5],
                    r[6],
                    r[7],
                    f"{r[8]:,.2f}",
                ),
            )
            total_sold += r[5]
            total_defect += r[6]
            total_rev += r[8]

        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        cash_rev = payment_totals.get("cash", 0.0)
        card_rev = payment_totals.get("card", 0.0)
        current_cashbox = self.db.get_cash_balance()

        summary_frame = ttk.LabelFrame(
            win, text="Финансовые и складские итоги смены", padding=10
        )
        summary_frame.pack(fill=tk.X, padx=10, pady=10)

        line1 = (
            f"📦 Всего продано: {total_sold} шт.   |   "
            f"⚠️ Списано брака: {total_defect} шт.   |   "
            f"💰 Общая выручка: {total_rev:,.2f} руб."
        )
        ttk.Label(
            summary_frame, text=line1, font=("Arial", 10, "bold")
        ).pack(anchor=tk.W, pady=2)

        line2 = (
            f"💵 Оплата наличными: {cash_rev:,.2f} руб.   |   "
            f"💳 Оплата по карте: {card_rev:,.2f} руб.   |   "
            f"🏦 Фактический остаток наличных в кассе: {current_cashbox:,.2f} руб."
        )
        ttk.Label(
            summary_frame,
            text=line2,
            font=("Arial", 10, "bold"),
            foreground="darkblue",
        ).pack(anchor=tk.W, pady=2)


if __name__ == "__main__":
    app_root = tk.Tk()
    app = AutoShopApp(app_root)
    app_root.mainloop()