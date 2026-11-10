import csv
import os
import re
import time
import webbrowser
from datetime import datetime
from smartcard.System import readers
from smartcard.util import toHexString

RUTA_DOCUMENTOS = os.path.join(os.path.expanduser("~"), "Documents")
ARCHIVO_CSV = os.path.join(RUTA_DOCUMENTOS, "registro_nfc.csv")

CMD_GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]

# Tabla estándar de prefijos NDEF URI (NFC Forum)
PREFIJOS_NDEF = {
    0x00: "",
    0x01: "http://www.",
    0x02: "https://www.",
    0x03: "http://",
    0x04: "https://",
    0x05: "tel:",
    0x06: "mailto:",
}


def leer_memoria_completa(conexion):
    """Lee las páginas de usuario (páginas 4 a 16) de la memoria NTAG215."""
    buffer_bytes = bytearray()

    for pagina in range(4, 16):
        # 1. Intentar lectura PC/SC estándar de 4 bytes por página
        cmd = [0xFF, 0xB0, 0x00, pagina, 0x04]
        try:
            datos, sw1, sw2 = conexion.transmit(cmd)
            if sw1 == 0x90 and sw2 == 0x00:
                buffer_bytes.extend(datos)
                continue
        except Exception:
            pass

        # 2. Fallback: comando de lectura directa de 16 bytes (READ 0x30)
        try:
            cmd_16b = [0xFF, 0xB0, 0x00, pagina, 0x10]
            datos, sw1, sw2 = conexion.transmit(cmd_16b)
            if sw1 == 0x90 and sw2 == 0x00:
                buffer_bytes.extend(datos)
                break
        except Exception:
            pass

    return buffer_bytes


def decodificar_url_ndef(buffer_bytes):
    """Decodifica el registro NDEF Tipo URI o extrae la URL por coincidencia de texto."""
    if not buffer_bytes:
        return None

    # Método 1: Búsqueda de estructura NDEF oficial [0x55 ('U') + Código Prefijo + Ruta]
    for i in range(len(buffer_bytes) - 3):
        if buffer_bytes[i] == 0x55:  # 'U' (URI Record Type)
            codigo_prefijo = buffer_bytes[i + 1]
            prefijo = PREFIJOS_NDEF.get(codigo_prefijo, "")

            # Los datos terminan en el delimitador 0xFE o al final del bloque
            resto = buffer_bytes[i + 2 :].split(b"\xfe")[0]
            try:
                url_cuerpo = resto.decode("utf-8", errors="ignore")
                url_completa = prefijo + url_cuerpo
                url_limpia = "".join(
                    c for c in url_completa if c.isprintable() and c != "\x00"
                ).strip()
                if url_limpia.startswith("http"):
                    return url_limpia
            except Exception:
                pass

    # Método 2: Extracción directa si el enlace ya contiene 'http' en texto plano
    texto_crudo = "".join(chr(b) for b in buffer_bytes if 32 <= b <= 126)
    match = re.search(r"https?://[^\s\x00\xfe]+", texto_crudo)
    if match:
        return match.group(0)

    # Método 3: Si guardó el dominio sin protocolo explícito
    match_dominio = re.search(r"solucioneshc\.com[^\s\x00\xfe]*", texto_crudo)
    if match_dominio:
        return "https://" + match_dominio.group(0)

    return None


def registrar_en_csv(uid, url):
    fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existe = os.path.exists(ARCHIVO_CSV)

    try:
        with open(
            ARCHIVO_CSV, mode="a", newline="", encoding="utf-8-sig"
        ) as f:
            escritor = csv.writer(f, delimiter=";")
            if not existe:
                escritor.writerow(
                    ["Fecha y Hora", "UID Tarjeta", "Enlace / URL", "Estado"]
                )
            escritor.writerow(
                [fecha_hora, uid, url or "Sin URL", "Lectura Exitosa"]
            )
    except PermissionError:
        print(f"[AVISO] Cierra '{ARCHIVO_CSV}' en Excel para actualizarlo.")
    except Exception as e:
        print(f"[ERROR CSV] {e}")


def iniciar():
    disponibles = readers()
    if not disponibles:
        print("ERROR: No se detectó ningún lector conectado al PC.")
        return

    lector = disponibles[0]
    print("================================================================")
    print(f" LECTOR ACTIVO : {lector}")
    print(f" REGISTRO CSV  : {ARCHIVO_CSV}")
    print(" MODO          : LECTURA DE URL Y APERTURA DE NAVEGADOR")
    print("================================================================\n")
    print("Acerca tu tarjeta NFC al lector...\n")

    ultimo_uid = None

    while True:
        try:
            conexion = lector.createConnection()
            conexion.connect()

            # Leer UID
            datos, sw1, sw2 = conexion.transmit(CMD_GET_UID)

            if sw1 == 0x90 and sw2 == 0x00:
                uid_actual = toHexString(datos).replace(" ", "")

                if uid_actual != ultimo_uid:
                    print(f"-> Tarjeta detectada (UID: {uid_actual})")

                    # Extraer el Registro 1 (URL)
                    memoria = leer_memoria_completa(conexion)
                    url_detectada = decodificar_url_ndef(memoria)

                    if url_detectada:
                        print(f"-> URL Encontrada: {url_detectada}")
                        print("-> Abriendo navegador...")
                        webbrowser.open_new_tab(url_detectada)
                    else:
                        print("-> No se pudo extraer la URL de la memoria.")

                    # Guardar registro en el archivo de Excel
                    registrar_en_csv(uid_actual, url_detectada)
                    ultimo_uid = uid_actual

            conexion.disconnect()

        except Exception:
            # Se resetea cuando levantas la tarjeta del lector
            ultimo_uid = None

        time.sleep(0.4)


if __name__ == "__main__":
    iniciar()