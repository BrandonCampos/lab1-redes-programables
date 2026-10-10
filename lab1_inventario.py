
#!/usr/bin/env python3

import os
import re
import yaml
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

    try:
        with ConnectHandler(**parametros) as conexion:

            print(f"\n[OK] Conectado a {equipo['nombre']}")

            estado = obtener_estado(
                conexion,
                equipo["device_type"],
            )

            print("\nEstado estructurado:")
            print("--------------------")

            print(f"Nombre: {estado['nombre']}")
            print(f"Uptime: {estado['uptime']}")

            print("\nInterfaces:")

            for interfaz in estado["interfaces"]:
                print(
                    f"  {interfaz['interface']} "
                    f"{interfaz['address']}"
                )

            print("\nRuta por defecto:")

            if estado["ruta_default"]:
                print(
                    f"  Gateway: "
                    f"{estado['ruta_default']['gateway']}"
                )
            else:
                print("  No encontrada")

            return estado

    except NetmikoAuthenticationException:
        print(
            f"[ERROR] Falló la autenticación "
            f"en {equipo['nombre']}"
        )

    except NetmikoTimeoutException:
        print(
            f"[ERROR] No se pudo conectar "
            f"a {equipo['nombre']}"
        )

    except Exception as error:
        print(
            f"[ERROR] {equipo['nombre']}: {error}"
        )

    return None


def main():
    equipos = cargar_inventario()

    for equipo in equipos:
        conectar_equipo(equipo)


if __name__ == "__main__":
    main()
