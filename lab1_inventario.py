
#!/usr/bin/env python3

import os
import re
import yaml
import json
from datetime import datetime
from getpass import getpass

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
)


# ============================================================
# Comandos por tipo de dispositivo
# ============================================================

COMANDOS = {
    "mikrotik_routeros": {
        "identidad": "/system identity print",
        "recursos": "/system resource print",
        "interfaces": "/ip address print terse",
        "ruta_default": "/ip route print terse where dst-address=0.0.0.0/0",
    }
}


def cargar_inventario():
    with open("inventario.yaml", "r", encoding="utf-8") as archivo:
        datos = yaml.safe_load(archivo)

    return datos["equipos"]


def obtener_password(nombre_equipo):
    variable = "LAB_PASS_" + nombre_equipo.upper().replace("-", "_")

    password = os.getenv(variable)

    if password:
        return password

    return getpass(f"Contraseña para {nombre_equipo}: ")


def texto_colon_a_dict(texto):
    """
    Convierte líneas del tipo:
        name: BRANDON-LAB1
        uptime: 1h20m30s

    en un diccionario.
    """

    datos = {}

    for linea in texto.splitlines():
        linea = linea.strip()

        if ":" in linea:
            clave, valor = linea.split(":", 1)

            clave = clave.strip()
            valor = valor.strip()

            datos[clave] = valor

    return datos


def parsear_terse(texto):
    """
    Convierte la salida 'print terse' de RouterOS
    en una lista de diccionarios.
    """

    registros = []

    for linea in texto.splitlines():
        linea = linea.strip()

        if not linea:
            continue

        registro = {}

        pares = re.findall(r'([\w-]+)=("[^"]*"|\S+)', linea)

        for clave, valor in pares:
            registro[clave] = valor.strip('"')

        if registro:
            registros.append(registro)

    return registros


def obtener_estado(conexion, device_type):
    comandos = COMANDOS[device_type]

    # --------------------------------------------------------
    # Nombre del equipo
    # --------------------------------------------------------

    salida_identidad = conexion.send_command(
        comandos["identidad"]
    )

    identidad = texto_colon_a_dict(salida_identidad)

    nombre = identidad.get("name", "desconocido")

    # --------------------------------------------------------
    # Uptime
    # --------------------------------------------------------

    salida_recursos = conexion.send_command(
        comandos["recursos"]
    )

    recursos = texto_colon_a_dict(salida_recursos)

    uptime = recursos.get("uptime", "desconocido")

    # --------------------------------------------------------
    # Interfaces e IP
    # --------------------------------------------------------

    salida_interfaces = conexion.send_command(
        comandos["interfaces"]
    )

    interfaces_crudas = parsear_terse(salida_interfaces)

    interfaces = []

    for interfaz in interfaces_crudas:
        interfaces.append(
            {
                "interface": interfaz.get("interface"),
                "address": interfaz.get("address"),
                "network": interfaz.get("network"),
            }
        )

    # --------------------------------------------------------
    # Ruta por defecto
    # --------------------------------------------------------

    salida_ruta = conexion.send_command(
        comandos["ruta_default"]
    )

    rutas = parsear_terse(salida_ruta)

    ruta_default = {}

    if rutas:
        ruta_default = {
            "dst_address": rutas[0].get("dst-address"),
            "gateway": rutas[0].get("gateway"),
            "routing_table": rutas[0].get("routing-table"),
        }

    # --------------------------------------------------------
    # Estado estructurado
    # --------------------------------------------------------

    estado = {
        "nombre": nombre,
        "uptime": uptime,
        "interfaces": interfaces,
        "ruta_default": ruta_default,
    }

    return estado


def conectar_equipo(equipo):
    password = obtener_password(equipo["nombre"])

    parametros = {
        "device_type": equipo["device_type"],
        "host": equipo["host"],
        "username": equipo["usuario"],
        "password": password,
        "session_log": f"logs/{equipo['nombre']}.log",
    }

    resultado = {
        "equipo": equipo["nombre"],
        "ip": equipo["host"],
        "fecha_hora": datetime.now().isoformat(timespec="seconds"),
        "estado": "error",
        "datos": {},
    }

    try:
        with ConnectHandler(**parametros) as conexion:
            print(f"\n[OK] Conectado a {equipo['nombre']}")

            estado = obtener_estado(
                conexion,
                equipo["device_type"],
            )

            resultado["estado"] = "ok"
            resultado["datos"] = estado

    except NetmikoAuthenticationException:
        mensaje = "error de autenticacion"
        print(f"[ERROR] {equipo['nombre']}: {mensaje}")
        resultado["estado"] = mensaje

    except NetmikoTimeoutException:
        mensaje = "error de conexion"
        print(f"[ERROR] {equipo['nombre']}: {mensaje}")
        resultado["estado"] = mensaje

    except Exception as error:
        mensaje = str(error)
        print(f"[ERROR] {equipo['nombre']}: {mensaje}")
        resultado["estado"] = mensaje

    return resultado

def main():
    equipos = cargar_inventario()

    reporte = []

    for equipo in equipos:
        resultado = conectar_equipo(equipo)
        reporte.append(resultado)

    # Guardar reporte JSON
    with open("reporte_estado.json", "w", encoding="utf-8") as archivo:
        json.dump(
            reporte,
            archivo,
            indent=4,
            ensure_ascii=False,
        )

    print("\nReporte guardado en reporte_estado.json")

    # Tabla resumen
    print("\nRESUMEN")
    print("-" * 90)

    print(
        f"{'EQUIPO':<18}"
        f"{'IP':<18}"
        f"{'ESTADO':<22}"
        f"{'INTERFACES':<15}"
        f"{'GATEWAY':<17}"
    )

    print("-" * 90)

    for item in reporte:
        datos = item.get("datos", {})

        interfaces = datos.get("interfaces", [])
        cantidad_interfaces = len(interfaces)

        ruta = datos.get("ruta_default", {})
        gateway = ruta.get("gateway") or "-"

        print(
            f"{item['equipo']:<18}"
            f"{item['ip']:<18}"
            f"{item['estado']:<22}"
            f"{cantidad_interfaces:<15}"
            f"{gateway:<17}"
        )



if __name__ == "__main__":
    main()
