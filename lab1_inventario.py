
import os
import yaml
from getpass import getpass

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoTimeoutException,
    NetmikoAuthenticationException
)


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


def conectar_equipo(equipo):
    password = obtener_password(equipo["nombre"])

    parametros = {
        "device_type": equipo["device_type"],
        "host": equipo["host"],
        "username": equipo["usuario"],
        "password": password,
        "session_log": f"logs/{equipo['nombre']}.log"
    }

    try:
        with ConnectHandler(**parametros) as conexion:
            print(f"[OK] Conectado a {equipo['nombre']}")

            salida = conexion.send_command("/system identity print")

            print(salida)

    except NetmikoAuthenticationException:
        print(f"[ERROR] Falló la autenticación en {equipo['nombre']}")

    except NetmikoTimeoutException:
        print(f"[ERROR] No se pudo conectar a {equipo['nombre']}")

    except Exception as error:
        print(f"[ERROR] {equipo['nombre']}: {error}")


def main():
    equipos = cargar_inventario()

    for equipo in equipos:
        conectar_equipo(equipo)


if __name__ == "__main__":
    main()

