FROM alpine:3.20

LABEL org.opencontainers.image.authors="rcastberg"

RUN apk add --update --no-cache python3 ipmitool py3-requests && ln -sf python3 /usr/bin/python

ADD Dell_iDRAC_fan_controller.py /Dell_iDRAC_fan_controller.py

RUN chmod 0777 /Dell_iDRAC_fan_controller.py

CMD ["/Dell_iDRAC_fan_controller.py"]
