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
            # Склад товаров (остатки поштучно)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE,
                    name TEXT NOT NULL,
                    category TEXT,
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
            # Баланс движения за смену: Начало + Приход - Расход = Конец
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS shift_details (
                    shift_id INTEGER,
                    product_id INTEGER,
                    initial_qty INTEGER DEFAULT 0,
                    received_qty INTEGER DEFAULT 0,
                    sold_qty INTEGER DEFAULT 0,
                    final_qty INTEGER DEFAULT 0,
                    PRIMARY KEY(shift_id, product_id)
                )
            """)
            self.seed_sample_data()

    def generate_next_sku(self):
        """Автоматическая генерация следующего уникального артикула вида SKU-000001"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(id) FROM inventory")
        max_id = cursor.fetchone()[0]
        next_num = (max_id or 0) + 1
        return f"SKU-{next_num:06d}"

    def seed_sample_data(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM inventory")
        if cursor.fetchone()[0] == 0:
            sample = [
                ("SKU-000001", "Масло моторное 5W-40 4L", "Масла", 2500.0, 6),
                ("SKU-000002", "Фильтр масляный W712", "Фильтры", 450.0, 12),
                ("SKU-000003", "Колодки тормозные передние", "Тормозная система", 1800.0, 4),
                ("SKU-000004", "Свеча зажигания Nickel", "Зажигание", 350.0, 20),
                ("SKU-000005", "Антифриз G12+ 5L", "Охлаждение", 1200.0, 5)
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
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("INSERT INTO shifts (start_time, is_active) VALUES (?, 1)", (now,))
            shift_id = cursor.lastrowid
            
            # Фиксируем начальные остатки имеющихся позиций
            cursor.execute("SELECT id, current_qty FROM inventory")
            items = cursor.fetchall()
            for prod_id, qty in items:
                cursor.execute("""
                    INSERT INTO shift_details (shift_id, product_id, initial_qty, received_qty, sold_qty, final_qty)
                    VALUES (?, ?, ?, 0, 0, ?)
                """, (shift_id, prod_id, qty, qty))
        return shift_id

    def add_inventory_item(self, name, category, price, qty, shift_id=None):
        sku = self.generate_next_sku()
        with self.conn:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO inventory (sku, name, category, price, current_qty)
                VALUES (?, ?, ?, ?, ?)
            """, (sku, name, category, price, qty))
            prod_id = cursor.lastrowid

            # Если смена активна, учитываем как приход (поставку) в текущей смене
            if shift_id:
                cursor.execute("""
                    INSERT INTO shift_details (shift_id, product_id, initial_qty, received_qty, sold_qty, final_qty)
                    VALUES (?, ?, 0, ?, 0, ?)
                """, (shift_id, prod_id, qty, qty))
        return sku

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
            return True, "Успешно"

    def delete_items(self, product_ids, shift_id=None):
        with self.conn:
            cursor = self.conn.cursor()
            placeholders = ",".join("?" for _ in product_ids)
            cursor.execute(f"DELETE FROM inventory WHERE id IN ({placeholders})", product_ids)
            if shift_id:
                cursor.execute(f"DELETE FROM shift_details WHERE shift_id = ? AND product_id IN ({placeholders})", [shift_id] + list(product_ids))

    def close_shift(self, shift_id):
        with self.conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.conn.execute("UPDATE shifts SET is_active = 0, end_time = ? WHERE id = ?", (now, shift_id))

    def get_shift_summary(self, shift_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT i.sku, i.name, sd.initial_qty, sd.received_qty, sd.sold_qty, sd.final_qty, (sd.sold_qty * i.price) as revenue
            FROM shift_details sd
            JOIN inventory i ON i.id = sd.product_id
            WHERE sd.shift_id = ?
        """, (shift_id,))
        return cursor.fetchall()

    def get_all_inventory(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, sku, name, category, price, current_qty FROM inventory ORDER BY id DESC")
        return cursor.fetchall()


class AddProductDialog(tk.Toplevel):
    """Модальное окно добавления нового товара/поставки без ввода артикула"""
    def __init__(self, parent, db, shift_id, on_success):
        super().__init__(parent)
        self.title("Оприходование нового товара (Поставка)")
        self.geometry("450x300")
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

        ttk.Label(form, text="Категория:").grid(row=1, column=0, sticky=tk.W, pady=6)
        self.entry_cat = ttk.Entry(form, width=32)
        self.entry_cat.grid(row=1, column=1, pady=6)

        ttk.Label(form, text="Стоимость / Цена (руб.):").grid(row=2, column=0, sticky=tk.W, pady=6)
        self.entry_price = ttk.Entry(form, width=32)
        self.entry_price.grid(row=2, column=1, pady=6)

        ttk.Label(form, text="Количество (шт.):").grid(row=3, column=0, sticky=tk.W, pady=6)
        self.entry_qty = ttk.Entry(form, width=32)
        self.entry_qty.grid(row=3, column=1, pady=6)

        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=20)

        ttk.Button(btn_frame, text="Сохранить и принять", command=self.save_product).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=self.destroy).pack(side=tk.LEFT, padx=5)

    def save_product(self):
        name = self.entry_name.get().strip()
        cat = self.entry_cat.get().strip()
        price_str = self.entry_price.get().strip().replace(",", ".")
        qty_str = self.entry_qty.get().strip()

        if not name:
            messagebox.showerror("Ошибка", "Наименование детали обязательно!", parent=self)
            return

        try:
            price = float(price_str)
            qty = int(qty_str)
            if price < 0 or qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Цена должна быть неотрицательной, а количество — целым числом больше нуля!", parent=self)
            return

        sku = self.db.add_inventory_item(name, cat, price, qty, self.shift_id)
        messagebox.showinfo("Товар добавлен", f"Товар успешно зарегистрирован!\nПрисвоен артикул: {sku}", parent=self)
        self.on_success()
        self.destroy()


class AutoShopApp:
    """Главный интерфейс программы"""
    def __init__(self, root):
        self.root = root
        self.root.title("АРМ Автомагазина — Учет поштучных остатков и расхода")
        self.root.geometry("980x600")
        self.db = AutoShopDB()
        self.current_shift = self.db.get_active_shift()

        self.setup_menu()
        self.setup_ui()
        self.refresh_table()

    def setup_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        self.shift_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Управление сменой", menu=self.shift_menu)
        self.update_menu_items()

    def update_menu_items(self):
        self.shift_menu.delete(0, tk.END)
        if self.current_shift:
            self.shift_menu.add_command(label="Завершить текущую смену...", command=self.confirm_close_shift)
        else:
            self.shift_menu.add_command(label="Открыть новую смену", command=self.open_new_shift)

    def setup_ui(self):
        # Верхняя панель со статусом смены
        status_frame = ttk.Frame(self.root, padding=(12, 8), relief=tk.RIDGE)
        status_frame.pack(fill=tk.X, padx=10, pady=6)

        self.lbl_shift_status = ttk.Label(status_frame, text="", font=("Arial", 11, "bold"))
        self.lbl_shift_status.pack(side=tk.LEFT)
        self.update_status_ui()

        # Таблица остатков (включен множественный выбор selectmode="extended")
        table_frame = ttk.Frame(self.root, padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "sku", "name", "category", "price", "qty")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("id", text="ID")
        self.tree.heading("sku", text="Артикул (авто)")
        self.tree.heading("name", text="Наименование детали")
        self.tree.heading("category", text="Категория")
        self.tree.heading("price", text="Стоимость (руб.)")
        self.tree.heading("qty", text="Остаток (поштучно)")

        self.tree.column("id", width=45, anchor=tk.CENTER)
        self.tree.column("sku", width=120, anchor=tk.CENTER)
        self.tree.column("name", width=340)
        self.tree.column("category", width=140)
        self.tree.column("price", width=110, anchor=tk.E)
        self.tree.column("qty", width=130, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Нижняя панель действий
        bottom_frame = ttk.Frame(self.root, padding=10)
        bottom_frame.pack(fill=tk.X)

        ttk.Button(bottom_frame, text="Продать выбранный товар...", command=self.handle_sale_dialog).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom_frame, text="+ Поставка / Новый товар", command=self.open_add_product_dialog).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom_frame, text="Удалить выбранные товары", command=self.handle_delete_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom_frame, text="Обновить список", command=self.refresh_table).pack(side=tk.RIGHT, padx=6)

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
        messagebox.showinfo("Смена открыта", f"Смена #{shift_id} успешно начата.\nВсе текущие остатки зафиксированы.")

    def confirm_close_shift(self):
        """Предупреждение перед закрытием смены"""
        confirm = messagebox.askyesno(
            "Подтверждение закрытия смены",
            "Вы действительно хотите завершить текущую смену?\n\n"
            "После этого будет сформирован итоговый отчёт по расходу за смену, "
            "а продажа товаров будет приостановлена до открытия новой смены.",
            icon=messagebox.WARNING
        )
        if confirm:
            shift_id = self.current_shift[0]
            summary = self.db.get_shift_summary(shift_id)
            self.db.close_shift(shift_id)
            self.current_shift = None
            self.update_status_ui()
            self.show_summary_window(summary)

    def handle_sale_dialog(self):
        """Окно ввода количества для списания при продаже"""
        if not self.current_shift:
            messagebox.showwarning("Внимание", "Нельзя списать товар при закрытой смене! Сначала откройте новую смену.")
            return

        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите товар из таблицы для продажи!")
            return

        if len(selected) > 1:
            messagebox.showwarning("Внимание", "Для продажи выберите одну позицию (массовый выбор предназначен для удаления).")
            return

        item_values = self.tree.item(selected[0])["values"]
        product_id = item_values[0]
        name = item_values[2]
        current_qty = item_values[5]

        # Всплывающее окно ввода с возможностью отмены
        qty_input = simpledialog.askinteger(
            "Продажа / Списание товара",
            f"Товар: {name}\nВ наличии: {current_qty} шт.\n\nВведите количество для продажи (шт.):",
            parent=self.root,
            minvalue=1,
            maxvalue=current_qty
        )

        if qty_input is not None:
            success, msg = self.db.sell_item(self.current_shift[0], product_id, qty_input)
            if success:
                self.refresh_table()
                messagebox.showinfo("Успешно", f"Продано {qty_input} шт. детали «{name}».")
            else:
                messagebox.showerror("Ошибка", msg)

    def handle_delete_selected(self):
        """Удаление одного или нескольких выбранных товаров"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите в таблице товары, которые требуется удалить.\n(Можно удерживать Ctrl или Shift для выбора нескольких позиций).")
            return

        count = len(selected)
        confirm = messagebox.askyesno(
            "Удаление товаров",
            f"Вы точно хотите удалить выбранные позиции ({count} шт.) со склада?\n"
            "Это действие необратимо!",
            icon=messagebox.WARNING
        )
        if confirm:
            ids_to_delete = [self.tree.item(item)["values"][0] for item in selected]
            shift_id = self.current_shift[0] if self.current_shift else None
            self.db.delete_items(ids_to_delete, shift_id)
            self.refresh_table()
            messagebox.showinfo("Успешно", f"Удалено позиций: {count}.")

    def open_add_product_dialog(self):
        shift_id = self.current_shift[0] if self.current_shift else None
        AddProductDialog(self.root, self.db, shift_id, on_success=self.refresh_table)

    def refresh_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for item in self.db.get_all_inventory():
            self.tree.insert("", tk.END, values=item)

    def show_summary_window(self, summary_data):
        """Итоговая ведомость расхода за смену"""
        win = tk.Toplevel(self.root)
        win.title("Ведомость расхода товаров за смену")
        win.geometry("860x420")

        ttk.Label(win, text="Сводный отчёт расхода за смену", font=("Arial", 12, "bold"), padding=10).pack()

        cols = ("sku", "name", "init", "recv", "sold", "final", "rev")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        tree.heading("sku", text="Артикул")
        tree.heading("name", text="Наименование детали")
        tree.heading("init", text="Начало (шт.)")
        tree.heading("recv", text="Приход (шт.)")
        tree.heading("sold", text="Расход (шт.)")
        tree.heading("final", text="Конец (шт.)")
        tree.heading("rev", text="Сумма (руб.)")

        tree.column("sku", width=110, anchor=tk.CENTER)
        tree.column("name", width=250)
        tree.column("init", width=85, anchor=tk.CENTER)
        tree.column("recv", width=85, anchor=tk.CENTER)
        tree.column("sold", width=85, anchor=tk.CENTER)
        tree.column("final", width=85, anchor=tk.CENTER)
        tree.column("rev", width=100, anchor=tk.E)

        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        total_sold = 0
        total_rev = 0.0
        for row in summary_data:
            tree.insert("", tk.END, values=row)
            total_sold += row[4]
            total_rev += row[6]

        info = f"Всего израсходовано/продано: {total_sold} шт. | Общая выручка: {total_rev:,.2f} руб."
        ttk.Label(win, text=info, font=("Arial", 10, "bold"), padding=10).pack()


if __name__ == "__main__":
    app_root = tk.Tk()
    app = AutoShopApp(app_root)
    app_root.mainloop()