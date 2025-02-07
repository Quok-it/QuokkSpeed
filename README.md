PREREQUISITES:

Have the nvidia-dcgm.service daemon running (install dcgm on the host machine)

Run with python3 dcgmReaderTest.py

SEND TO MONGODB DATABASE:

1. sudo apt install python3-pymongo
2. sudo apt install python3-dnspython
3. python3 dcgmReaderToDB.py
4. sudo apt install python3-dotenv