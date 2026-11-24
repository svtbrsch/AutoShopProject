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
            # Справочник категорий
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                )
            """)
            # Склад товаров
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price REAL NOT NULL,
                    current_qty INTEGER NOT NULL CHECK(current_qty >= 0)
                )
            """)
            # Журнал смен
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS shifts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            # Баланс движения за смену с учётом брака/возврата
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS shift_details (
                    shift_id INTEGER,
                    product_id INTEGER,
                    initial_qty INTEGER DEFAULT 0,
                    received_qty INTEGER DEFAULT 0,
                    sold_qty INTEGER DEFAULT 0,
                    defective_qty INTEGER DEFAULT 0,
                    final_qty INTEGER DEFAULT 0,
                    PRIMARY KEY(shift_id, product_id)
                )
            """)
            self.seed_sample_data()

    def seed_sample_data(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM categories")
        if cursor.fetchone()[0] == 0:
            default_cats = ["Масла и тех. жидкости", "Фильтры", "Тормозная система", "Зажигание", "Подвеска", "Кузов"]
            cursor.executemany("INSERT INTO categories (name) VALUES (?)", [(c,) for c in default_cats])

        cursor.execute("SELECT COUNT(*) FROM inventory")
        if cursor.fetchone()[0] == 0:
            sample = [
                ("SKU-000001", "Масло моторное 5W-40 4L", "Масла и тех. жидкости", 2500.0, 8),
                ("SKU-000002", "Фильтр масляный W712", "Фильтры", 450.0, 15),
                ("SKU-000003", "Колодки тормозные передние", "Тормозная система", 1800.0, 5),
                ("SKU-000004", "Свеча зажигания Nickel", "Зажигание", 350.0, 24),
                ("SKU-000005", "Антифриз G12+ 5L", "Масла и тех. жидкости", 1200.0, 6)
            ]
            self.conn.executemany(
                "INSERT INTO inventory (sku, name, category, price, current_qty) VALUES (?, ?, ?, ?, ?)",
                sample
            )
            self.conn.commit()

    # --- Категории ---
    def get_categories(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM categories ORDER BY name ASC")
        return [row[0] for row in cursor.fetchall()]

    def add_category(self, name):
        try:
            with self.conn:
                self.conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
            return True, "Категория добавлена"
        except sqlite3.IntegrityError:
            return False, "Такая категория уже существует!"

    def delete_category(self, name):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM inventory WHERE category = ?", (name,))
        if cursor.fetchone()[0] > 0:
            return False, "Нельзя удалить категорию, к которой привязаны существующие товары!"
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE name = ?", (name,))
        return True, "Категория удалена"

    # --- Товары и остатки ---
    def generate_next_sku(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(id) FROM inventory")
        max_id = cursor.fetchone()[0]
        next_num = (max_id or 0) + 1
        return f"SKU-{next_num:06d}"

    def get_all_inventory(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, sku, name, category, price, current_qty FROM inventory ORDER BY id DESC")
        return cursor.fetchall()

    def add_inventory_item(self, name, category, price, qty, shift_id=None):
        sku = self.generate_next_sku()
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO inventory (sku, name, category, price, current_qty)
                VALUES (?, ?, ?, ?, ?)
            """, (sku, name, category, price, qty))
            prod_id = cursor.lastrowid

            if shift_id:
                cursor.execute("""
                    INSERT INTO shift_details (shift_id, product_id, initial_qty, received_qty, sold_qty, defective_qty, final_qty)
                    VALUES (?, ?, 0, ?, 0, 0, ?)
                """, (shift_id, prod_id, qty, qty))
        return sku

    def update_product_field(self, product_id, field_name, new_val):
        allowed_fields = {"name", "price", "category"}
        if field_name not in allowed_fields:
            return False
        with self.conn:
            self.conn.execute(f"UPDATE inventory SET {field_name} = ? WHERE id = ?", (new_val, product_id))
        return True

    def delete_items(self, product_ids, shift_id=None):
        with self.conn:
            cursor = self.conn.cursor()
            placeholders = ",".join("?" for _ in product_ids)
            cursor.execute(f"DELETE FROM inventory WHERE id IN ({placeholders})", product_ids)
            if shift_id:
                cursor.execute(f"DELETE FROM shift_details WHERE shift_id = ? AND product_id IN ({placeholders})", [shift_id] + list(product_ids))

    # --- Смены и операции ---
    def get_active_shift(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, start_time FROM shifts WHERE is_active = 1")
        return cursor.fetchone()

    def open_shift(self):
        with self.conn:
            cursor = self.conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("INSERT INTO shifts (start_time, is_active) VALUES (?, 1)", (now,))
            shift_id = cursor.lastrowid
            
            cursor.execute("SELECT id, current_qty FROM inventory")
            items = cursor.fetchall()
            for prod_id, qty in items:
                cursor.execute("""
                    INSERT INTO shift_details (shift_id, product_id, initial_qty, received_qty, sold_qty, defective_qty, final_qty)
                    VALUES (?, ?, ?, 0, 0, 0, ?)
                """, (shift_id, prod_id, qty, qty))
        return shift_id

    def sell_item(self, shift_id, product_id, qty):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT current_qty FROM inventory WHERE id = ?", (product_id,))
            res = cursor.fetchone()
            if not res or res[0] < qty:
                return False, f"Недостаточно товара на складе! В наличии: {res[0] if res else 0} шт."

            cursor.execute("UPDATE inventory SET current_qty = current_qty - ? WHERE id = ?", (qty, product_id))
            cursor.execute("""
                UPDATE shift_details 
                SET sold_qty = sold_qty + ?, final_qty = final_qty - ? 
                WHERE shift_id = ? AND product_id = ?
            """, (qty, qty, shift_id, product_id))
            return True, "Успешно списано при продаже"

    def register_defect(self, shift_id, product_id, qty):
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("SELECT current_qty FROM inventory WHERE id = ?", (product_id,))
            res = cursor.fetchone()
            if not res or res[0] < qty:
                return False, f"Недостаточно товара для списания брака! В наличии: {res[0] if res else 0} шт."

            cursor.execute("UPDATE inventory SET current_qty = current_qty - ? WHERE id = ?", (qty, product_id))
            cursor.execute("""
                UPDATE shift_details 
                SET defective_qty = defective_qty + ?, final_qty = final_qty - ? 
                WHERE shift_id = ? AND product_id = ?
            """, (qty, qty, shift_id, product_id))
            return True, "Товар списан в брак / возврат"

    def close_shift(self, shift_id):
        with self.conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.conn.execute("UPDATE shifts SET is_active = 0, end_time = ? WHERE id = ?", (now, shift_id))

    def get_shift_summary(self, shift_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT i.sku, i.name, sd.initial_qty, sd.received_qty, sd.sold_qty, sd.defective_qty, sd.final_qty, (sd.sold_qty * i.price) as revenue
            FROM shift_details sd
            JOIN inventory i ON i.id = sd.product_id
            WHERE sd.shift_id = ?
        """, (shift_id,))
        return cursor.fetchall()


class CategoriesDialog(tk.Toplevel):
    """Окно управления справочником категорий"""
    def __init__(self, parent, db, on_change_callback):
        super().__init__(parent)
        self.title("Управление категориями")
        self.geometry("380x380")
        self.resizable(False, False)
        self.grab_set()

        self.db = db
        self.on_change_callback = on_change_callback

        ttk.Label(self, text="Список доступных категорий:", font=("Arial", 10, "bold")).pack(pady=8)

        frame_list = ttk.Frame(self, padding=8)
        frame_list.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(frame_list, font=("Arial", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        self.load_categories()

        # Панель добавления
        add_frame = ttk.Frame(self, padding=8)
        add_frame.pack(fill=tk.X)
        self.entry_cat = ttk.Entry(add_frame)
        self.entry_cat.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(add_frame, text="Добавить", command=self.add_cat).pack(side=tk.LEFT)

        # Панель удаления
        del_frame = ttk.Frame(self, padding=8)
        del_frame.pack(fill=tk.X)
        ttk.Button(del_frame, text="Удалить выбранную категорию", command=self.delete_cat).pack(fill=tk.X)

    def load_categories(self):
        self.listbox.delete(0, tk.END)
        for cat in self.db.get_categories():
            self.listbox.insert(tk.END, cat)

    def add_cat(self):
        val = self.entry_cat.get().strip()
        if not val:
            messagebox.showwarning("Внимание", "Введите название категории!", parent=self)
            return
        ok, msg = self.db.add_category(val)
        if ok:
            self.entry_cat.delete(0, tk.END)
            self.load_categories()
            self.on_change_callback()
        else:
            messagebox.showerror("Ошибка", msg, parent=self)

    def delete_cat(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("Внимание", "Выберите категорию из списка для удаления!", parent=self)
            return
        cat_name = self.listbox.get(sel[0])
        ok, msg = self.db.delete_category(cat_name)
        if ok:
            self.load_categories()
            self.on_change_callback()
        else:
            messagebox.showerror("Ошибка", msg, parent=self)


class AddProductDialog(tk.Toplevel):
    """Окно прихода нового товара с выпадающим списком категорий"""
    def __init__(self, parent, db, shift_id, on_success):
        super().__init__(parent)
        self.title("Оприходование нового товара (Поставка)")
        self.geometry("460x300")
        self.resizable(False, False)
        self.grab_set()

        self.db = db
        self.shift_id = shift_id
        self.on_success = on_success

        form = ttk.Frame(self, padding=20)
        form.pack(fill=tk.BOTH, expand=True)

        ttk.Label(form, text="Наименование детали:").grid(row=0, column=0, sticky=tk.W, pady=6)
        self.entry_name = ttk.Entry(form, width=32)
        self.entry_name.grid(row=0, column=1, pady=6)

        ttk.Label(form, text="Категория (выбор):").grid(row=1, column=0, sticky=tk.W, pady=6)
        categories = self.db.get_categories()
        self.combo_cat = ttk.Combobox(form, values=categories, state="readonly", width=30)
        self.combo_cat.grid(row=1, column=1, pady=6)
        if categories:
            self.combo_cat.current(0)

        ttk.Label(form, text="Стоимость / Цена (руб.):").grid(row=2, column=0, sticky=tk.W, pady=6)
        self.entry_price = ttk.Entry(form, width=32)
        self.entry_price.grid(row=2, column=1, pady=6)

        ttk.Label(form, text="Количество (шт.):").grid(row=3, column=0, sticky=tk.W, pady=6)
        self.entry_qty = ttk.Entry(form, width=32)
        self.entry_qty.grid(row=3, column=1, pady=6)
        self.entry_qty.insert(0, "1")

        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=18)

        ttk.Button(btn_frame, text="Сохранить и принять", command=self.save_product).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=self.destroy).pack(side=tk.LEFT, padx=5)

    def save_product(self):
        name = self.entry_name.get().strip()
        cat = self.combo_cat.get()
        price_str = self.entry_price.get().strip().replace(",", ".")
        qty_str = self.entry_qty.get().strip()

        if not name:
            messagebox.showerror("Ошибка", "Наименование детали обязательно!", parent=self)
            return
        if not cat:
            messagebox.showerror("Ошибка", "Выберите категорию из списка!", parent=self)
            return

        try:
            price = float(price_str)
            qty = int(qty_str)
            if price < 0 or qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Цена должна быть неотрицательной, а количество — целым положительным числом!", parent=self)
            return

        sku = self.db.add_inventory_item(name, cat, price, qty, self.shift_id)
        messagebox.showinfo("Товар добавлен", f"Товар успешно зарегистрирован!\nПрисвоен артикул: {sku}", parent=self)
        self.on_success()
        self.destroy()


class AutoShopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("АРМ Автомагазина — Учет остатков, продаж и брака")
        self.root.geometry("1040x630")
        self.db = AutoShopDB()
        self.current_shift = self.db.get_active_shift()

        self.setup_menu()
        self.setup_ui()
        self.setup_context_menu()
        self.refresh_table()

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # Меню смен
        self.shift_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Управление сменой", menu=self.shift_menu)
        self.update_menu_items()

        # Меню справочников
        ref_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Справочники", menu=ref_menu)
        ref_menu.add_command(label="Управление категориями...", command=self.open_categories_manager)

    def update_menu_items(self):
        self.shift_menu.delete(0, tk.END)
        if self.current_shift:
            self.shift_menu.add_command(label="Завершить текущую смену...", command=self.confirm_close_shift)
        else:
            self.shift_menu.add_command(label="Открыть новую смену", command=self.open_new_shift)

    def setup_ui(self):
        # Панель статуса
        status_frame = ttk.Frame(self.root, padding=(12, 8), relief=tk.RIDGE)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        self.lbl_shift_status = ttk.Label(status_frame, text="", font=("Arial", 11, "bold"))
        self.lbl_shift_status.pack(side=tk.LEFT)
        self.update_status_ui()

        # Панель поиска и фильтрации
        filter_frame = ttk.LabelFrame(self.root, text="Поиск и фильтрация", padding=(10, 5))
        filter_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(filter_frame, text="Быстрый поиск (деталь/артикул):").pack(side=tk.LEFT, padx=5)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.apply_filter())
        self.entry_search = ttk.Entry(filter_frame, textvariable=self.search_var, width=28)
        self.entry_search.pack(side=tk.LEFT, padx=5)

        ttk.Label(filter_frame, text="Категория:").pack(side=tk.LEFT, padx=(15, 5))
        self.filter_cat_var = tk.StringVar(value="Все категории")
        self.combo_filter_cat = ttk.Combobox(filter_frame, textvariable=self.filter_cat_var, state="readonly", width=24)
        self.combo_filter_cat.pack(side=tk.LEFT, padx=5)
        self.combo_filter_cat.bind("<<ComboboxSelected>>", lambda e: self.apply_filter())
        self.update_category_filter_list()

        ttk.Button(filter_frame, text="Сбросить фильтры", command=self.reset_filters).pack(side=tk.RIGHT, padx=5)

        # Таблица товаров
        table_frame = ttk.Frame(self.root, padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "sku", "name", "category", "price", "qty")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("id", text="ID")
        self.tree.heading("sku", text="Артикул")
        self.tree.heading("name", text="Наименование детали")
        self.tree.heading("category", text="Категория")
        self.tree.heading("price", text="Стоимость (руб.)")
        self.tree.heading("qty", text="Остаток (шт.)")

        self.tree.column("id", width=45, anchor=tk.CENTER)
        self.tree.column("sku", width=120, anchor=tk.CENTER)
        self.tree.column("name", width=340)
        self.tree.column("category", width=170)
        self.tree.column("price", width=110, anchor=tk.E)
        self.tree.column("qty", width=110, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Панель кнопок действий
        bottom_frame = ttk.Frame(self.root, padding=10)
        bottom_frame.pack(fill=tk.X)

        ttk.Button(bottom_frame, text="🛒 Продать товар...", command=self.handle_sale_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom_frame, text="⚠️ Списать брак / Возврат...", command=self.handle_defect_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom_frame, text="+ Поставка / Приход", command=self.open_add_product_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom_frame, text="🗑 Удалить выбранные", command=self.handle_delete_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom_frame, text="Обновить список", command=self.refresh_table).pack(side=tk.RIGHT, padx=4)

    def setup_context_menu(self):
        """Контекстное меню по клику правой кнопкой мыши"""
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Изменить наименование...", command=self.edit_name)
        self.context_menu.add_command(label="Изменить цену...", command=self.edit_price)
        self.context_menu.add_command(label="Изменить категорию...", command=self.edit_category)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Списать брак / возврат...", command=self.handle_defect_dialog)

        # Привязка для Windows / Linux (<Button-3>) и macOS (<Button-2> / <Control-Button-1>)
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Button-2>", self.show_context_menu)

    def show_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            # Если строка не входила в уже выделенные, выделяем только её
            if row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
            self.context_menu.post(event.x_root, event.y_root)

    # --- Обработчики контекстного меню ---
    def get_single_selected_item(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Товар не выбран!")
            return None
        return self.tree.item(sel[0])["values"]

    def edit_name(self):
        item = self.get_single_selected_item()
        if not item:
            return
        prod_id, current_name = item[0], item[2]
        new_name = simpledialog.askstring("Редактирование", "Введите новое наименование детали:", initialvalue=current_name, parent=self.root)
        if new_name and new_name.strip():
            self.db.update_product_field(prod_id, "name", new_name.strip())
            self.refresh_table()

    def edit_price(self):
        item = self.get_single_selected_item()
        if not item:
            return
        prod_id, current_price = item[0], item[4]
        new_price_str = simpledialog.askstring("Редактирование", "Введите новую стоимость (руб.):", initialvalue=str(current_price), parent=self.root)
        if new_price_str:
            try:
                new_price = float(new_price_str.replace(",", "."))
                if new_price < 0:
                    raise ValueError
                self.db.update_product_field(prod_id, "price", new_price)
                self.refresh_table()
            except ValueError:
                messagebox.showerror("Ошибка", "Некорректное значение стоимости!")

    def edit_category(self):
        item = self.get_single_selected_item()
        if not item:
            return
        prod_id, current_cat = item[0], item[3]
        categories = self.db.get_categories()

        win = tk.Toplevel(self.root)
        win.title("Смена категории")
        win.geometry("340x140")
        win.grab_set()

        ttk.Label(win, text=f"Деталь: {item[2]}").pack(pady=6)
        combo = ttk.Combobox(win, values=categories, state="readonly", width=30)
        combo.pack(pady=6)
        if current_cat in categories:
            combo.set(current_cat)
        elif categories:
            combo.current(0)

        def save():
            selected_cat = combo.get()
            if selected_cat:
                self.db.update_product_field(prod_id, "category", selected_cat)
                self.refresh_table()
                win.destroy()

        ttk.Button(win, text="Сохранить", command=save).pack(pady=8)

    # --- Списание брака ---
    def handle_defect_dialog(self):
        if not self.current_shift:
            messagebox.showwarning("Внимание", "Списание брака регистрируется в рамках активной смены! Откройте смену.")
            return

        item = self.get_single_selected_item()
        if not item:
            return

        prod_id, name, stock_qty = item[0], item[2], item[5]
        if stock_qty <= 0:
            messagebox.showwarning("Внимание", "Данного товара нет на складе для списания!")
            return

        qty_input = simpledialog.askinteger(
            "Списание брака / Возврат",
            f"Товар: {name}\nВ наличии: {stock_qty} шт.\n\nВведите количество бракованного товара (шт.):",
            parent=self.root,
            initialvalue=1,
            minvalue=1,
            maxvalue=stock_qty
        )

        if qty_input is not None:
            reason = simpledialog.askstring("Причина брака/возврата", "Укажите причину (дефект упаковки, заводской брак, течь и т.д.):", parent=self.root)
            success, msg = self.db.register_defect(self.current_shift[0], prod_id, qty_input)
            if success:
                self.refresh_table()
                messagebox.showinfo("Списание оформлено", f"Списано {qty_input} шт. в брак/возврат.\nПричина: {reason or 'Не указана'}")
            else:
                messagebox.showerror("Ошибка", msg)

    # --- Продажа (по умолчанию 1 шт.) ---
    def handle_sale_dialog(self):
        if not self.current_shift:
            messagebox.showwarning("Внимание", "Нельзя списать товар при закрытой смене! Сначала откройте новую смену.")
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите товар из таблицы для продажи!")
            return

        if len(selected) > 1:
            messagebox.showwarning("Внимание", "Для продажи выберите одну позицию.")
            return

        item_values = self.tree.item(selected[0])["values"]
        prod_id, name, current_qty = item_values[0], item_values[2], item_values[5]

        if current_qty <= 0:
            messagebox.showwarning("Внимание", "Товар закончился на складе!")
            return

        qty_input = simpledialog.askinteger(
            "Продажа товара",
            f"Товар: {name}\nВ наличии: {current_qty} шт.\n\nКоличество для продажи (шт.):",
            parent=self.root,
            initialvalue=1,
            minvalue=1,
            maxvalue=current_qty
        )

        if qty_input is not None:
            success, msg = self.db.sell_item(self.current_shift[0], prod_id, qty_input)
            if success:
                self.refresh_table()
                messagebox.showinfo("Успешно", f"Продано {qty_input} шт. детали «{name}».")
            else:
                messagebox.showerror("Ошибка", msg)

    # --- Фильтрация и поиск ---
    def update_category_filter_list(self):
        cats = ["Все категории"] + self.db.get_categories()
        self.combo_filter_cat["values"] = cats
        if self.filter_cat_var.get() not in cats:
            self.filter_cat_var.set("Все категории")

    def reset_filters(self):
        self.search_var.set("")
        self.filter_cat_var.set("Все категории")
        self.refresh_table()

    def apply_filter(self):
        query = self.search_var.get().strip().lower()
        cat_filter = self.filter_cat_var.get()

        for row in self.tree.get_children():
            self.tree.delete(row)

        for item in self.db.get_all_inventory():
            sku, name, cat = str(item[1]).lower(), str(item[2]).lower(), item[3]
            match_search = (query in name) or (query in sku) if query else True
            match_cat = (cat_filter == "Все категории") or (cat == cat_filter)

            if match_search and match_cat:
                self.tree.insert("", tk.END, values=item)

    # --- Множественное удаление ---
    def handle_delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите позиции для удаления (зажмите Ctrl или Shift для выбора нескольких).")
            return

        count = len(selected)
        confirm = messagebox.askyesno(
            "Удаление товаров",
            f"Вы точно хотите удалить выбранные позиции ({count} шт.) со склада?\nДействие необратимо!",
            icon=messagebox.WARNING
        )
        if confirm:
            ids_to_delete = [self.tree.item(item)["values"][0] for item in selected]
            shift_id = self.current_shift[0] if self.current_shift else None
            self.db.delete_items(ids_to_delete, shift_id)
            self.refresh_table()
            messagebox.showinfo("Успешно", f"Удалено позиций: {count}.")

    def open_categories_manager(self):
        CategoriesDialog(self.root, self.db, on_change_callback=self.on_categories_changed)

    def on_categories_changed(self):
        self.update_category_filter_list()
        self.refresh_table()

    def open_add_product_dialog(self):
        shift_id = self.current_shift[0] if self.current_shift else None
        AddProductDialog(self.root, self.db, shift_id, on_success=self.refresh_table)

    def refresh_table(self):
        self.apply_filter()

    # --- Смена и итоги ---
    def update_status_ui(self):
        if self.current_shift:
            self.lbl_shift_status.config(
                text=f"Смена активна (ID: #{self.current_shift[0]}, открыта: {self.current_shift[1]})",
                foreground="#0B6623"
            )
        else:
            self.lbl_shift_status.config(
                text="Смена закрыта. Для начала работы откройте смену через меню «Управление сменой».",
                foreground="#B22222"
            )
        self.update_menu_items()

    def open_new_shift(self):
        shift_id = self.db.open_shift()
        self.current_shift = self.db.get_active_shift()
        self.update_status_ui()
        messagebox.showinfo("Смена открыта", f"Смена #{shift_id} успешно начата.\nВсе остатки зафиксированы.")

    def confirm_close_shift(self):
        confirm = messagebox.askyesno(
            "Подтверждение закрытия смены",
            "Вы действительно хотите завершить текущую смену?\n\nБудет сформирован итоговый отчёт по расходу и браку.",
            icon=messagebox.WARNING
        )
        if confirm:
            shift_id = self.current_shift[0]
            summary = self.db.get_shift_summary(shift_id)
            self.db.close_shift(shift_id)
            self.current_shift = None
            self.update_status_ui()
            self.show_summary_window(summary)

    def show_summary_window(self, summary_data):
        """Итоговый отчёт по расходу за смену с браком"""
        win = tk.Toplevel(self.root)
        win.title("Ведомость расхода и брака за смену")
        win.geometry("980x440")

        ttk.Label(win, text="Сводный отчёт по движению товаров за смену", font=("Arial", 12, "bold"), padding=10).pack()

        cols = ("sku", "name", "init", "recv", "sold", "defect", "final", "rev")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        tree.heading("sku", text="Артикул")
        tree.heading("name", text="Наименование детали")
        tree.heading("init", text="Начало")
        tree.heading("recv", text="Приход")
        tree.heading("sold", text="Продано")
        tree.heading("defect", text="Брак/Возврат")
        tree.heading("final", text="Остаток")
        tree.heading("rev", text="Выручка (руб.)")

        tree.column("sku", width=110, anchor=tk.CENTER)
        tree.column("name", width=260)
        tree.column("init", width=75, anchor=tk.CENTER)
        tree.column("recv", width=75, anchor=tk.CENTER)
        tree.column("sold", width=80, anchor=tk.CENTER)
        tree.column("defect", width=95, anchor=tk.CENTER)
        tree.column("final", width=75, anchor=tk.CENTER)
        tree.column("rev", width=110, anchor=tk.E)

        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        total_sold = 0
        total_defect = 0
        total_rev = 0.0

        for row in summary_data:
            tree.insert("", tk.END, values=row)
            total_sold += row[4]
            total_defect += row[5]
            total_rev += row[7]

        summary_text = (
            f"Всего продано: {total_sold} шт.  |  "
            f"Списано брака/возвратов: {total_defect} шт.  |  "
            f"Итоговая выручка: {total_rev:,.2f} руб."
        )
        ttk.Label(win, text=summary_text, font=("Arial", 11, "bold"), padding=10).pack()


if __name__ == "__main__":
    app_root = tk.Tk()
    app = AutoShopApp(app_root)
    app_root.mainloop()