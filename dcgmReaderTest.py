#RUN USING: sudo PYTHONPATH=/usr/local/dcgm/bindings/python3 /usr/bin/python3 /home/vader/quokkspeed/scripts/dcgmReaderTest.py

# Copyright (c) 2024, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from DcgmReader import *
import dcgm_fields
import time
import socket
import psutil
import re

fieldsToGrab = [
    dcgm_fields.DCGM_FI_DEV_NAME,
    dcgm_fields.DCGM_FI_DEV_BRAND,
    dcgm_fields.DCGM_FI_DEV_SERIAL,
    dcgm_fields.DCGM_FI_DEV_UUID,
    dcgm_fields.DCGM_FI_DEV_POWER_USAGE,
    dcgm_fields.DCGM_FI_DEV_GPU_TEMP,
    dcgm_fields.DCGM_FI_DEV_MEM_CLOCK,
    dcgm_fields.DCGM_FI_DEV_MEMORY_TEMP,
    dcgm_fields.DCGM_FI_DEV_POWER_USAGE_INSTANT,
    dcgm_fields.DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION,
    dcgm_fields.DCGM_FI_DEV_MEM_COPY_UTIL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL,
    dcgm_fields.DCGM_FI_DEV_PCIE_TX_THROUGHPUT,
    dcgm_fields.DCGM_FI_DEV_PCIE_RX_THROUGHPUT,
    #in newest version (4.0) this one is deprecated, it should be DCGM_FI_DEV_CLOCKS_EVENT_REASONS
    dcgm_fields.DCGM_FI_DEV_CLOCK_THROTTLE_REASONS,
    dcgm_fields.DCGM_FI_DEV_SM_CLOCK,
    dcgm_fields.DCGM_FI_DEV_GPU_UTIL,
    dcgm_fields.DCGM_FI_DEV_RETIRED_PENDING,
    dcgm_fields.DCGM_FI_DEV_RETIRED_SBE,
    dcgm_fields.DCGM_FI_DEV_RETIRED_DBE,
    dcgm_fields.DCGM_FI_DEV_ECC_SBE_VOL_TOTAL,
    dcgm_fields.DCGM_FI_DEV_ECC_DBE_VOL_TOTAL,
    dcgm_fields.DCGM_FI_DEV_ECC_SBE_AGG_TOTAL,
    dcgm_fields.DCGM_FI_DEV_ECC_DBE_AGG_TOTAL,
    dcgm_fields.DCGM_FI_DEV_PCIE_REPLAY_COUNTER,
    dcgm_fields.DCGM_FI_DEV_POWER_VIOLATION,
    dcgm_fields.DCGM_FI_DEV_THERMAL_VIOLATION,
    dcgm_fields.DCGM_FI_DEV_XID_ERRORS,
    dcgm_fields.DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_CRC_DATA_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_FB_TOTAL,   #framebuffer total
    dcgm_fields.DCGM_FI_DEV_FB_FREE,    #framebuffer free
    dcgm_fields.DCGM_FI_DEV_FB_USED,    #framebuffer used
    dcgm_fields.DCGM_FI_DEV_FB_RESERVED #framebuffer reserved
]

class FieldHandlerReader(DcgmReader):
    '''
        Override just this method to do something different per field. 
        This method is called once for each field for each GPU each 
        time that its Process() method is invoked, and it will be skipped
        for blank values and fields in the ignore list.
    '''
    def CustomFieldHandler(self, gpuId, fieldId, fieldTag, val):
        print('GPU %d %s(%d) = %s' % (gpuId, fieldTag, fieldId, val.value))

class DataHandlerReader(DcgmReader):
    '''
        Override just this method to handle the entire map of data in your own way. This 
        might be used if you want to iterate by field id and then GPU or something like that.
        This method is called once for each time the Process() method is invoked.
    '''
    def CustomDataHandler(self, fvs):
        for fieldId in self.m_publishFieldIds:
            if fieldId in self.m_dcgmIgnoreFields:
                continue
        
            out = 'Values for %s:' % (self.m_fieldIdToInfo[fieldId].tag)
            wasBlank = True
            for gpuId in list(fvs.keys()):
                gpuFv = fvs[gpuId]
                val = gpuFv[fieldId][-1]

                #Skip blank values. Otherwise, we'd have to insert a placeholder blank value based on the fieldId
                if val.isBlank:
                    continue

                wasBlank = False
                append = " GPU%d=%s" % (gpuId, val.value)
                out = out + append

            if wasBlank == False:
                print(out)

'''
    hostname         : Port for the nv-hostengine (default port 0000:5555)
    field_ids        : List of the field ids to publish. If it isn't specified, our default list is used.
    update_frequency : Frequency of update in microseconds. Defauls to 10 seconds or 10000000 microseconds
    keep_time        : Max time to keep data from NVML, in seconds. Default is 3600.0 (1 hour)
    ignores          : List of the field ids we want to query but not publish.
'''
def DcgmReaderDictionary(hostname, field_ids, update_frequency, keep_time, ignores, field_groups):
    # Instantiate a DcgmReader object
    dr = DcgmReader(hostname=hostname, fieldIds=field_ids, updateFrequency=update_frequency, maxKeepAge=keep_time, ignoreList=ignores, fieldGroupName=field_groups)
    print("connecting to port " + hostname)
    # Get the default list of fields as a dictionary of dictionaries:
    # gpuId -> field name -> field value
    data = dr.GetLatestGpuValuesAsFieldNameDict()

    # Print the dictionary
    for gpuId in data:
        for fieldName in data[gpuId]:
            print("For gpu %s field %s=%s" % (str(gpuId), fieldName, data[gpuId][fieldName]))

def getIp():
    # Regex for wlp
    wireless_pattern = re.compile(r'(wlan|wifi|^wl)', re.IGNORECASE)

    for iface, addr_list in psutil.net_if_addrs().items():
        if wireless_pattern.search(iface):
            for addr in addr_list:
                if addr.family == socket.AF_INET:
                    return addr.address
    return None

def main(): 
    print('Quokking...')
    hn = getIp()
    print(hn)
    hostname = hn + ":5555"
    print(hostname)
    try:
        while True:
            DcgmReaderDictionary(hostname=hostname, field_ids=fieldsToGrab, update_frequency=1000000, keep_time=3600.0, ignores=[], field_groups='dcgm_fieldgroupdata')
            time.sleep(1)
    except KeyboardInterrupt:
        print('quokked!')
    



if __name__ == '__main__':
    main()