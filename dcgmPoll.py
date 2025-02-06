import pydcgm
import dcgm_structs
import dcgm_fields

def collect_telemetry():
    dcgmHandle = pydcgm.DcgmHandle()
    dcgmSystem = dcgmHandle.GetSystem()
    supportedGPUs = dcgmSystem.discovery.GetAllSupportedGpuIds()
    
    for gpuId in supportedGPUs:
        # Collect specific telemetry fields
        fields = [
            DcgmSystemFields,
            dcgmSystem.DCGM_FI_DEV_GPU_UTIL,
            dcgm_fields.DCGM_FI_DEV_MEM_COPY_UTIL,
            dcgm_fields.DCGM_FI_DEV_MEMORY_TEMP,
            dcgm_fields.DCGM_FI_DEV_POWER_USAGE
        ]
        
        values = dcgmSystem.GetLatestValuesForFields(gpuId, fields)
        
        print(f"GPU {gpuId} Telemetry:")
        for field, value in zip(fields, values):
            print(f"  {dcgm_fields.DcgmFieldGetEntityGroupString(field)}: {value}")

if __name__ == "__main__":
    collect_telemetry()