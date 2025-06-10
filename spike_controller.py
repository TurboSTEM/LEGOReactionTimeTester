import serial
import serial.tools.list_ports
import json
import pyautogui
import time
import os
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

# --- Configuration File ---
CONFIG_FILE = 'spike_config.json'

# --- Rich Console Initialization ---
console = Console()

def load_config():
    """Loads configuration from a JSON file."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(serial_number, threshold):
    """Saves configuration to a JSON file."""
    config = {
        'serial_number': serial_number,
        'trigger_threshold': threshold
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)
    console.print(f"[green]Configuration saved to {CONFIG_FILE}[/green]")

def select_device():
    """
    Scans for serial devices, displays them in a table, and prompts the user
    to select one.
    """
    console.print("[bold cyan]Scanning for connected serial devices...[/bold cyan]")
    comports = list(serial.tools.list_ports.comports())

    if not comports:
        console.print("[bold red]No serial devices found. Please ensure your Spike Prime is connected.[/bold red]")
        return None, None

    table = Table(title="Available Serial Devices")
    table.add_column("Index", style="magenta", no_wrap=True)
    table.add_column("Device", style="cyan")
    table.add_column("Serial Number", style="yellow")
    table.add_column("Description", style="green")

    for i, port in enumerate(comports):
        table.add_row(str(i + 1), port.device, port.serial_number or "N/A", port.description)

    console.print(table)

    while True:
        try:
            choice = IntPrompt.ask(
                "[bold]Enter the index number of your LEGO Spike Prime[/bold]",
                console=console
            )
            if 1 <= choice <= len(comports):
                selected_port = comports[choice - 1]
                console.print(f"You selected: [cyan]{selected_port.device}[/cyan] with serial [yellow]{selected_port.serial_number}[/yellow]")
                return selected_port.device, selected_port.serial_number
            else:
                console.print("[red]Invalid index. Please try again.[/red]")
        except ValueError:
            console.print("[red]Invalid input. Please enter a number.[/red]")


def main():
    """
    Main function to orchestrate device connection, configuration, and monitoring.
    """
    console.rule("[bold blue]LEGO Spike Prime Mouse Controller[/bold blue]")
    config = load_config()
    spike_port = None
    serial_number = None

    # --- Device Selection Logic ---
    if 'serial_number' in config and config['serial_number']:
        if Confirm.ask(f"Found saved serial number [yellow]{config['serial_number']}[/yellow]. Use this device?"):
            # Verify the device is still available
            comports = serial.tools.list_ports.comports()
            found = False
            for port in comports:
                if port.serial_number == config['serial_number']:
                    spike_port = port.device
                    serial_number = port.serial_number
                    console.print(f"[green]Found saved Spike Prime at: {spike_port}[/green]")
                    found = True
                    break
            if not found:
                console.print("[bold red]Saved device not found. Please select a new one.[/bold red]")
                spike_port, serial_number = select_device()
        else:
            spike_port, serial_number = select_device()
    else:
        spike_port, serial_number = select_device()

    if not spike_port or not serial_number:
        return

    # --- Trigger Threshold Configuration ---
    console.print("\n[bold]Configure the trigger threshold (0-10 Newtons).[/bold]")
    console.print("A lower value makes the sensor more sensitive.")
    console.print("[bold yellow]Tip:[/bold yellow] Use a value of [cyan]1[/cyan] for an 'instant press' that triggers on any touch.")

    default_threshold = config.get('trigger_threshold', 1)
    trigger_threshold = IntPrompt.ask(
        "Enter trigger threshold",
        default=default_threshold,
        console=console
    )

    save_config(serial_number, trigger_threshold)

    # --- Sensor Monitoring ---
    monitor_device(spike_port, trigger_threshold)


def monitor_device(port, threshold):
    """
    Connects to the Spike Prime, monitors the force sensor, and triggers mouse clicks.
    """
    try:
        recv_buf = bytearray()
        is_pressed = False

        console.rule(f"[bold green]Connecting to {port}...[/bold green]")
        with serial.Serial(port, 115200, timeout=1) as ser:
            console.print("[bold green]Successfully connected![/bold green]")
            console.print("Press [bold]CTRL+C[/bold] to exit.")
            time.sleep(1) # Give it a moment to stabilize

            with Live(console=console, screen=False, auto_refresh=False, vertical_overflow="visible") as live:
                while True:
                    try:
                        # Request sensor data by sending a message.
                        # This assumes the Spike is running a program that sends sensor data upon receiving any byte.
                        data = ser.read_until(b'\r')

                        if not data:
                            continue

                        recv_buf.extend(data)

                        if b'\r' in recv_buf:
                            lines = recv_buf.split(b'\r')
                            for line in lines[:-1]:
                                if not line:
                                    continue
                                try:
                                    message = json.loads(line.decode('utf-8'))
                                    # Expected format from Spike: {"force": N} or similar.
                                    # This part must be adapted to the EXACT JSON your Spike sends.
                                    # For this example, we assume the original logic's data structure.
                                    # {"m": 0, "p": [[63, [force_value, is_touched]]]}
                                    if message['m'] == 0:
                                        for item in message['p']:
                                            if isinstance(item, list) and item[0] == 63: # Port F, Force Sensor
                                                force_value = item[1][0] # Force in Newtons (0-10)
                                                is_touched = item[1][1] == 1 # Boolean for touched state

                                                # Update live display
                                                panel_content = Text(f"Live Force: {force_value:.2f} N", justify="center", style="bold")
                                                live.update(Panel(panel_content, title="Sensor Status", border_style="blue"), refresh=True)

                                                # Click logic
                                                if threshold == 1: # Instant press mode
                                                    if is_touched and not is_pressed:
                                                        is_pressed = True
                                                        pyautogui.click()
                                                        console.log("Click! (Instant Press)")
                                                    elif not is_touched and is_pressed:
                                                        is_pressed = False
                                                else: # Threshold mode
                                                    if force_value >= threshold and not is_pressed:
                                                        is_pressed = True
                                                        pyautogui.click()
                                                        console.log(f"Click! (Threshold: {threshold}N)")
                                                    elif force_value < threshold and is_pressed:
                                                        is_pressed = False
                                except (json.JSONDecodeError, KeyError, IndexError):
                                    # Ignore malformed data, but log it for debugging
                                    # console.log(f"[dim]Could not parse: {line}[/dim]")
                                    pass
                            recv_buf = recv_buf[recv_buf.rfind(b'\r')+1:]

                    except serial.SerialException:
                        console.print("[bold red]Error: Serial device disconnected.[/bold red]")
                        break
                    except KeyboardInterrupt:
                        console.print("\n[bold yellow]Exiting program.[/bold yellow]")
                        return

    except serial.SerialException as e:
        console.print(f"[bold red]Error: Could not open serial port '{port}'.[/bold red]")
        console.print(f"[dim]{e}[/dim]")
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred: {e}[/bold red]")


if __name__ == "__main__":
    main()
