"""Legacy search repositories: trusted query structure, user values always bound."""


def search_services(c, status, search):
    conditions, params = [], []
    if status in ("Nueva", "Contactada", "Aceptada", "Finalizada", "Descartada"):
        conditions.append("estado=?")
        params.append(status)
    if search:
        conditions.append("(empresa LIKE ? OR nombre LIKE ? OR correo LIKE ? OR servicio_nombre LIKE ?)")
        params.extend([f"%{search[:100]}%"] * 4)
    if getattr(c, "dialect", "sqlite") == "postgresql":
        conditions = [part.replace(" LIKE ", " ILIKE ") for part in conditions]
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return c.execute(f"SELECT * FROM servicios_solicitados{where} ORDER BY id DESC", params).fetchall()


def search_accounts(c, status, search):
    conditions, params = [], []
    if search:
        conditions.append("(nombre LIKE ? OR correo LIKE ? OR plan LIKE ?)")
        params.extend([f"%{search[:100]}%"] * 3)
    if status in ("activos", "desactivados"):
        conditions.append("activo=?")
        params.append(1 if status == "activos" else 0)
    if getattr(c, "dialect", "sqlite") == "postgresql":
        conditions = [part.replace(" LIKE ", " ILIKE ") for part in conditions]
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return c.execute(f"SELECT * FROM clientes{where} ORDER BY nombre", params).fetchall()
