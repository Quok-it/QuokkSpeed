import subprocess
import time
import pydcgm
import dcgm_structs

def set_gpu_power_limit(gpu_id, power_limit_watts):
    """
    Sets the GPU power limit using DCGM.
    :param gpu_id: GPU index (0, 1, etc.)
    :param power_limit_watts: New power limit in watts
    """
    try:
        dcgm_handle = pydcgm.DcgmHandle()
        dcgm_system = pydcgm.DcgmSystem(dcgm_handle)
        dcgm_system.SetGpuPowerLimit(gpu_id, power_limit_watts)
        print(f"✅ Successfully set GPU {gpu_id} power limit to {power_limit_watts}W")
    except Exception as e:
        print(f"❌ Error setting GPU power limit: {e}")

def get_gpu_info():
    """
    Retrieves GPU power usage & limits using `nvidia-smi`.
    """
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,power.limit", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True
        )
        gpus = []
        for line in output.stdout.strip().split("\n"):
            gpu_id, name, power_limit = line.split(", ")
            gpus.append({"id": int(gpu_id), "name": name, "power_limit": int(power_limit)})
        return gpus
    except Exception as e:
        print(f"❌ Error fetching GPU info: {e}")
        return []

def main():
    # Define new GPU power limit (Watts)
    NEW_POWER_LIMIT = 250

    # Fetch GPU info
    gpus = get_gpu_info()
    if not gpus:
        print("⚠️ No GPUs found!")
        return

    print("🔍 Current GPU Power Limits:")
    for gpu in gpus:
        print(f"  - GPU {gpu['id']}: {gpu['name']} -> {gpu['power_limit']}W")

    # Set new power limit
    for gpu in gpus:
        set_gpu_power_limit(gpu["id"], NEW_POWER_LIMIT)

    print("✅ GPU Power Policy Change Completed!")

if __name__ == "__main__":
    main()
