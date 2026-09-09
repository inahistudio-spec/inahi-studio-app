"""Named, parameterized SQL used by legacy Flask controllers. Values stay bound."""

PERMITIR_INTENTO_1 = 'UPDATE rate_limits SET intentos=intentos+1 WHERE clave=?'

PERMITIR_INTENTO_2 = 'INSERT INTO rate_limits(clave,inicio,intentos) VALUES(?,?,1) ON CONFLICT(clave) DO UPDATE SET inicio=excluded.inicio,intentos=1'

PERMITIR_INTENTO_3 = 'SELECT inicio,intentos FROM rate_limits WHERE clave=?'

CREAR_TOKEN_VERIFICACION_1 = 'DELETE FROM email_verifications WHERE cliente_id=? OR expira<?'

CREAR_TOKEN_VERIFICACION_2 = 'INSERT INTO email_verifications(token,cliente_id,expira) VALUES(?,?,?)'

INICIALIZAR_BASE_DATOS_1 = 'CREATE TABLE IF NOT EXISTS stripe_webhook_events(\n            event_id TEXT PRIMARY KEY,\n            event_type TEXT NOT NULL,\n            processed_at TEXT NOT NULL\n        )'

CLIENT_REQUIRED_1 = 'SELECT id,activo,subscription_status,trial_end FROM clientes WHERE id=?'

CLIENT_REQUIRED_2 = "UPDATE clientes SET activo=0,subscription_status='prueba_finalizada' WHERE id=?"

INICIO_1 = '\n                    INSERT INTO consultas\n                    (empresa, correo, problema, token, respuesta)\n                    VALUES (?, ?, ?, ?, ?)\n                    '

CONSULTA_CLIENTE_1 = '\n            SELECT empresa, correo, problema, respuesta\n            FROM consultas\n            WHERE token = ?\n            '

ESTADO_CONSULTA_1 = 'SELECT respuesta FROM consultas WHERE token = ?'

CLIENTE_REGISTRO_1 = '\n                        INSERT INTO clientes\n                        (nombre, correo, contrasena, plan, activo, email_verificado)\n                        VALUES (?, ?, ?, ?, 0, 0)\n                        '

CLIENTE_REGISTRO_2 = 'UPDATE clientes SET plan_key=?, subscription_status=?, activo=?, creado=?, trial_end=?, legal_accepted_at=? WHERE correo=?'

CLIENTE_REGISTRO_3 = 'SELECT id FROM clientes WHERE correo=?'

VERIFICAR_EMAIL_1 = 'UPDATE email_verifications SET usado=1 WHERE token=?'

VERIFICAR_EMAIL_2 = "UPDATE clientes SET email_verificado=1,subscription_status='pendiente',\n                   activo=0,trial_end='',trial_slot=0,trial_queries_used=0 WHERE id=?"

VERIFICAR_EMAIL_3 = "UPDATE clientes SET email_verificado=1,subscription_status='prueba',\n                   activo=1,trial_end=?,trial_slot=1,trial_queries_used=0\n                   WHERE id=? AND (SELECT COUNT(*) FROM clientes WHERE trial_slot=1) < ?"

VERIFICAR_EMAIL_4 = 'SELECT v.cliente_id,v.expira,v.usado,c.plan_key FROM email_verifications v\n               JOIN clientes c ON c.id=v.cliente_id WHERE v.token=?'

VERIFICAR_EMAIL_5 = "UPDATE clientes SET email_verificado=1,subscription_status='lista_espera',\n                       activo=0,trial_end='',trial_slot=0 WHERE id=?"

VERIFICAR_EMAIL_6 = 'SELECT u.id,u.credential_version,o.id AS organization_id\n                FROM users u JOIN organizations o ON o.legacy_cliente_id=u.legacy_cliente_id\n                WHERE u.legacy_cliente_id=?'

RECUPERAR_CONTRASENA_1 = 'DELETE FROM password_resets WHERE cliente_id=? OR expira<?'

RECUPERAR_CONTRASENA_2 = 'INSERT INTO password_resets(token, cliente_id, expira) VALUES(?,?,?)'

RECUPERAR_CONTRASENA_3 = 'SELECT id FROM clientes WHERE correo=?'

NUEVA_CONTRASENA_1 = 'SELECT * FROM password_resets WHERE token=? AND usado=0'

NUEVA_CONTRASENA_2 = 'UPDATE clientes SET contrasena=? WHERE id=?'

NUEVA_CONTRASENA_3 = 'UPDATE password_resets SET usado=1 WHERE token=?'

CREAR_CHECKOUT_1 = 'SELECT * FROM clientes WHERE id=?'

PAGO_CORRECTO_1 = "UPDATE clientes SET activo=1, plan_key=?, plan=?, subscription_status='activa',\n               stripe_customer_id=?, stripe_subscription_id=? WHERE id=?"

FACTURACION_1 = 'SELECT stripe_customer_id FROM clientes WHERE id=?'

SERVICIOS_1 = 'INSERT INTO servicios_solicitados\n                    (servicio_key,servicio_nombre,precio,nombre,empresa,correo,telefono,mensaje,fecha)\n                    VALUES(?,?,?,?,?,?,?,?,?)'

CLIENTE_ACCESO_1 = 'SELECT * FROM clientes WHERE correo=?'

CLIENTE_ACCESO_2 = 'SELECT * FROM clientes WHERE id=?'

PORTAL_1 = 'SELECT * FROM clientes WHERE id=?'

PORTAL_2 = 'SELECT * FROM solicitudes WHERE cliente_id=? ORDER BY id DESC'

PORTAL_3 = 'SELECT * FROM citas WHERE cliente_id=? ORDER BY id DESC'

PORTAL_4 = 'SELECT * FROM diagnosticos WHERE cliente_id=?'

PORTAL_5 = 'SELECT id FROM estrategias_comerciales WHERE cliente_id=?'

PORTAL_6 = 'SELECT id FROM calendarios_contenido WHERE cliente_id=? AND periodo=?'

PORTAL_7 = 'SELECT COUNT(*) FROM solicitudes WHERE cliente_id=? AND fecha>=?'

DIAGNOSTICO_1 = 'INSERT INTO diagnosticos(cliente_id,web,google,redes,resenas,objetivos,puntuacion,actualizado)\n                         VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)\n                         ON CONFLICT(cliente_id) DO UPDATE SET web=excluded.web,google=excluded.google,\n                         redes=excluded.redes,resenas=excluded.resenas,objetivos=excluded.objetivos,\n                         puntuacion=excluded.puntuacion,actualizado=CURRENT_TIMESTAMP'

DIAGNOSTICO_2 = 'SELECT * FROM diagnosticos WHERE cliente_id=?'

ESTRATEGIA_COMERCIAL_1 = 'INSERT INTO estrategias_comerciales(cliente_id,respuestas,estrategia,actualizado)\n                   VALUES(?,?,?,?)\n                   ON CONFLICT(cliente_id) DO UPDATE SET respuestas=excluded.respuestas,\n                   estrategia=excluded.estrategia,actualizado=excluded.actualizado'

ESTRATEGIA_COMERCIAL_2 = 'SELECT nombre,plan_key FROM clientes WHERE id=?'

ESTRATEGIA_COMERCIAL_3 = 'SELECT * FROM estrategias_comerciales WHERE cliente_id=?'

CALENDARIO_CONTENIDOS_1 = 'INSERT INTO calendarios_contenido(cliente_id,periodo,contenido,creado) VALUES(?,?,?,?)'

CALENDARIO_CONTENIDOS_2 = 'UPDATE calendarios_contenido SET contenido=?,creado=? WHERE cliente_id=? AND periodo=?'

CALENDARIO_CONTENIDOS_3 = 'SELECT plan_key FROM clientes WHERE id=?'

CALENDARIO_CONTENIDOS_4 = 'SELECT respuestas FROM estrategias_comerciales WHERE cliente_id=?'

CALENDARIO_CONTENIDOS_5 = 'SELECT contenido FROM calendarios_contenido WHERE cliente_id=? AND periodo=?'

RESULTADOS_MENSUALES_1 = 'INSERT INTO resultados_mensuales\n                   (cliente_id,periodo,contactos,ventas,ingresos,resenas,notas,informe,creado)\n                   VALUES(?,?,?,?,?,?,?,?,?)\n                   ON CONFLICT(cliente_id,periodo) DO UPDATE SET contactos=excluded.contactos,\n                   ventas=excluded.ventas,ingresos=excluded.ingresos,resenas=excluded.resenas,\n                   notas=excluded.notas,informe=excluded.informe,creado=excluded.creado'

RESULTADOS_MENSUALES_2 = 'SELECT * FROM resultados_mensuales WHERE cliente_id=? AND periodo=?'

RESULTADOS_MENSUALES_3 = 'SELECT * FROM resultados_mensuales WHERE cliente_id=? AND periodo<? ORDER BY periodo DESC LIMIT 1'

SOLICITUD_CLIENTE_1 = 'INSERT INTO solicitudes(cliente_id,asunto,descripcion,respuesta,estado,fecha,origen_respuesta) VALUES(?,?,?,?,?,?,?)'

SOLICITUD_CLIENTE_2 = 'UPDATE clientes SET trial_queries_used=trial_queries_used+1\n                           WHERE id=? AND trial_slot=1 AND trial_queries_used<?'

SOLICITUD_CLIENTE_3 = 'SELECT plan_key,subscription_status,trial_slot,trial_queries_used FROM clientes WHERE id=?'

SOLICITUD_CLIENTE_4 = 'SELECT respuestas,estrategia FROM estrategias_comerciales WHERE cliente_id=?'

SOLICITUD_CLIENTE_5 = 'SELECT COUNT(*) FROM solicitudes WHERE cliente_id=? AND fecha>=?'

INFORMES_CLIENTE_1 = 'SELECT * FROM informes WHERE cliente_id=? ORDER BY id DESC'

CAMBIAR_CONTRASENA_1 = 'SELECT contrasena FROM clientes WHERE id=?'

CAMBIAR_CONTRASENA_2 = 'UPDATE clientes SET contrasena=? WHERE id=?'

SOLICITAR_CITA_1 = 'SELECT plan_key FROM clientes WHERE id=?'

SOLICITAR_CITA_2 = 'SELECT COUNT(*) FROM citas WHERE cliente_id=? AND fecha>=?'

SOLICITAR_CITA_3 = 'INSERT INTO citas(cliente_id,fecha,hora,modalidad,motivo) VALUES(?,?,?,?,?)'

SOLICITAR_CITA_4 = 'SELECT nombre,correo FROM clientes WHERE id=?'

PANEL_ADMIN_1 = 'SELECT * FROM servicios_solicitados ORDER BY id DESC LIMIT 4'

PANEL_ADMIN_2 = 'SELECT * FROM clientes ORDER BY id DESC LIMIT 4'

PANEL_ADMIN_3 = "SELECT ci.*,cl.nombre FROM citas ci JOIN clientes cl ON cl.id=ci.cliente_id\n               WHERE ci.estado='Pendiente' ORDER BY ci.fecha,ci.hora LIMIT 4"

PANEL_ADMIN_4 = 'SELECT COUNT(*) FROM clientes'

PANEL_ADMIN_5 = 'SELECT COUNT(*) FROM clientes WHERE activo=1'

PANEL_ADMIN_6 = "SELECT COUNT(*) FROM clientes WHERE subscription_status='prueba'"

PANEL_ADMIN_7 = "SELECT COUNT(*) FROM consultas WHERE COALESCE(respuesta,'')='' "

PANEL_ADMIN_8 = "SELECT COUNT(*) FROM solicitudes WHERE estado='Pendiente'"

PANEL_ADMIN_9 = "SELECT COUNT(*) FROM servicios_solicitados WHERE estado='Nueva'"

PANEL_ADMIN_10 = "SELECT COUNT(*) FROM citas WHERE estado='Pendiente'"

SERVICIOS_ADMIN_1 = 'UPDATE servicios_solicitados SET estado=? WHERE id=?'

VER_CONSULTAS_1 = 'UPDATE consultas SET respuesta = ? WHERE id = ?'

VER_CONSULTAS_2 = 'SELECT * FROM consultas ORDER BY id DESC'

VER_CONSULTAS_3 = 'SELECT empresa, correo, token, respuesta FROM consultas WHERE id = ?'

CREAR_CLIENTE_1 = '\n                    INSERT INTO clientes\n                    (nombre, correo, contrasena, plan, activo)\n                    VALUES (?, ?, ?, ?, 1)\n                    '

CREAR_CLIENTE_2 = 'SELECT id FROM clientes WHERE correo=?'

CAMBIAR_ESTADO_CLIENTE_1 = 'UPDATE clientes SET activo=CASE activo WHEN 1 THEN 0 ELSE 1 END WHERE id=?'

ELIMINAR_CLIENTE_1 = 'DELETE FROM password_resets WHERE cliente_id=?'

ELIMINAR_CLIENTE_2 = 'DELETE FROM diagnosticos WHERE cliente_id=?'

ELIMINAR_CLIENTE_3 = 'DELETE FROM estrategias_comerciales WHERE cliente_id=?'

ELIMINAR_CLIENTE_4 = 'DELETE FROM calendarios_contenido WHERE cliente_id=?'

ELIMINAR_CLIENTE_5 = 'DELETE FROM resultados_mensuales WHERE cliente_id=?'

ELIMINAR_CLIENTE_6 = 'DELETE FROM citas WHERE cliente_id=?'

ELIMINAR_CLIENTE_7 = 'DELETE FROM informes WHERE cliente_id=?'

ELIMINAR_CLIENTE_8 = 'DELETE FROM solicitudes WHERE cliente_id=?'

ELIMINAR_CLIENTE_9 = 'DELETE FROM clientes WHERE id=?'

ELIMINAR_CLIENTE_10 = "UPDATE organizations SET status='archived',updated_at=? WHERE id=?"

ELIMINAR_CLIENTE_11 = 'SELECT nombre,stripe_subscription_id,subscription_status FROM clientes WHERE id=?'

ELIMINAR_CLIENTE_12 = 'SELECT id FROM organizations WHERE legacy_cliente_id=?'

EDITAR_CLIENTE_1 = 'SELECT * FROM clientes WHERE id=?'

EDITAR_CLIENTE_2 = 'UPDATE clientes SET nombre=?,correo=?,plan=? WHERE id=?'

EDITAR_CLIENTE_3 = 'UPDATE clientes SET contrasena=? WHERE id=?'

SOLICITUDES_ADMIN_1 = "UPDATE solicitudes SET respuesta=?,estado='Respondida' WHERE id=?"

SOLICITUDES_ADMIN_2 = 'SELECT s.*,c.nombre FROM solicitudes s JOIN clientes c ON c.id=s.cliente_id ORDER BY s.id DESC'

CREAR_INFORME_1 = 'INSERT INTO informes(cliente_id, titulo, contenido) VALUES (?, ?, ?)'

CREAR_INFORME_2 = 'SELECT * FROM clientes ORDER BY nombre'

INFORMES_ADMIN_1 = 'SELECT i.*,c.nombre FROM informes i JOIN clientes c ON c.id=i.cliente_id ORDER BY i.id DESC'

CITAS_ADMIN_1 = 'SELECT ci.*,cl.nombre FROM citas ci JOIN clientes cl ON cl.id=ci.cliente_id ORDER BY ci.fecha,ci.hora'

CAMBIAR_ESTADO_CITA_1 = 'UPDATE citas SET estado=? WHERE id=?'
