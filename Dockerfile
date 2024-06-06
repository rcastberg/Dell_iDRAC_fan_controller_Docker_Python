FROM alpine:3.20

LABEL org.opencontainers.image.authors="rcastberg"

RUN apk add --update --no-cache python3 ipmitool py3-pip && ln -sf python3 /usr/bin/python

ADD requirements.txt  /requirements.txt

RUN pip install -r /requirements.txt --break-system-packages

ADD Dell_iDRAC_fan_controller.py /Dell_iDRAC_fan_controller.py

RUN chmod 0777 /Dell_iDRAC_fan_controller.py

CMD ["python3", "-u", "/Dell_iDRAC_fan_controller.py"]
