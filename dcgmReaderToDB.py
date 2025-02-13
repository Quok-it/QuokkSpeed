# RUN USING: python3 dcgmReaderToDB.py

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
import psutil
import socket
import re
import docker

import os
from dotenv import load_dotenv, dotenv_values
load_dotenv()

# sending telemetry to MongoDB database
from pymongo import MongoClient
from datetime import datetime, timezone

# connect to MongoDB Atlas
mongo_uri = os.getenv('MONGO_DATABASE')
client = MongoClient(mongo_uri)
db = client["gpu_monitoring"]

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
        curr_dict[gpuId] = val.value
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
    hostname         : Port for the nv-hostengine (port 0000:5555)
    field_ids        : List of the field ids to publish. If it isn't specified, our default list is used.
    update_frequency : Frequency of update in microseconds. Defauls to 10 seconds or 10000000 microseconds
    keep_time        : Max time to keep data from NVML, in seconds. Default is 3600.0 (1 hour)
    ignores          : List of the field ids we want to query but not publish.
'''
def DcgmReaderDictionary(hostname, field_ids, update_frequency, keep_time, ignores, field_groups):
    # Instantiate a DcgmReader object
    dr = DcgmReader(hostname=hostname, fieldIds=field_ids, updateFrequency=update_frequency, maxKeepAge=keep_time, ignoreList=ignores, fieldGroupName=field_groups)

    # Get the default list of fields as a dictionary of dictionaries:
    # gpuId -> field name -> field value
    data = dr.GetLatestGpuValuesAsFieldNameDict()
    # print("Data Retrieved: ", data)
    
    for gpuId, gpuData in data.items():
        gpu_uuid = gpuData.get("uuid", None)
        # print("gpu_uuid: ", gpu_uuid)
        if gpu_uuid is None:
            # UUID is missing --> error
            continue
        
        # get curr time in UTC
        now = datetime.now(timezone.utc)
        unix_timestamp = int(now.timestamp())  # convert to unix time
        
        # prep GPU data entry
        gpu_entry = {
            "gpu_uuid": gpu_uuid,
            "timestamp": now,  # human-readable time
            "unix_time": unix_timestamp,  # unix time
            "metrics_measured": {}
        }
        
        # store all metrics inside 'metrics_measured'
        for fieldName, values, in gpuData.items():
            latest_value = values # get most recent value
            print(fieldName)
            if latest_value not in [None, "", "N/A"]:
                gpu_entry["metrics_measured"][fieldName] = latest_value

        # Compute FB_UTIL (Framebuffer Utilization)
        fb_used = float(gpu_entry["metrics_measured"].get("framebuffer_used", 1))
        fb_total = float(gpu_entry["metrics_measured"].get("framebuffer_total", 1))

        print(f"FB_UTIL Calculated: ", round(fb_used / fb_total))
        # if fb_used is not None and fb_total not in [None, 0]:  # Avoid division by zero
        #     gpu_entry["metrics_measured"]["FB_UTIL"] = round(fb_used / fb_total)  # Store as percentage (rounded)

        # ensure 'primary key' is unique (gpu_uuid & timestamp)
        db.gpu_polling.update_one(
            {"gpu_uuid": gpu_entry["gpu_uuid"], "timestamp": gpu_entry["timestamp"]}, 
            {"$set": {
                "unix_time": gpu_entry["unix_time"],  # add unix time 
                "metrics_measured": gpu_entry["metrics_measured"]  # update only metrics
            }},
            upsert=True  # insert if not found
        )
        
        print(f"Data inserted for GPU: {gpu_uuid} at {gpu_entry['timestamp']} (Unix Time: {gpu_entry['unix_time']})")

    # # Print the dictionary
    # for gpuId in data:
    #     for fieldName in data[gpuId]:
    #         print("For gpu %s field %s=%s" % (str(gpuId), fieldName, data[gpuId][fieldName]))

def getIp():
    client = docker.from_env()
    # List all running containers
    containers = client.containers.list()
    prefix = "dcgm-daemon"
    for container in containers:
        # container.name typically returns something like "dcgm-daemon.<nomad_alloc>" 
        if container.name.startswith(prefix):
            ip = container.attrs["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
            print(f"Found container '{container.name}' with IP: {ip}")
            return ip
    print(f"No container found with prefix '{prefix}'")
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