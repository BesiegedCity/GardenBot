import json
import time
import os
import logging
import click
from pathlib import Path

from loguru import logger
from flask import Flask
from flask import request
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
CATALOG = Path("./weather_data")  # 存放本地天气信息缓存的位置
HOST = "0.0.0.0" # 设置为0.0.0.0以接收外网传来的HTTP消息
PORT = "5051" # 设置HTTP端口

WATERCTL_WTD_TIME = 30

waterctl_stat = '?'  # 1~2位字符标识浇水控制器工作状态 ?-离线 00-在线，空闲 1x-在线，正在浇灌x号区域
needwater = '00'  # 两位数字定义的浇水任务模式


# 定时清除浇水控制器在线状态标志
def waterctl_watchdog():
    global waterctl_stat
    msg = "控制器在线标志被清除"
    logger.info(msg)
    waterctl_stat = '?'

if not os.path.exists(CATALOG):
    os.mkdir(CATALOG)
scheduler = BackgroundScheduler()
wtd = scheduler.add_job(waterctl_watchdog, 'interval', seconds=WATERCTL_WTD_TIME, id='watchdog')  # 看门狗每隔10s，将浇水控制器在线状态写为?


def get_time():  # 返回秒级时间戳
    return int(time.time())


# 读取从远程传感器发回的温湿度信息
@app.route('/upload', methods=['POST'])
def upload():
    try:
        json_data = json.loads(request.get_data(as_text=True)) # {"temp":"25","humid":"2","rain":"1","wet":"1"}
        if json_data:
            temp = json_data['temp']
            humid = json_data['humid']
            wet = json_data['wet']
            rain = json_data['rain']
            json_data['time'] = get_time()

            year = str(time.localtime(time.time()).tm_year)
            month = str(time.localtime(time.time()).tm_mon)
            day = str(time.localtime(time.time()).tm_mday)
            logger.info("Temperature:%2s°C Humidity:%2s%% Wet:%2s Rained:%2s"
                        % (temp, humid, wet, rain))  # 在命令行中即时显示收到的信息
            with open(CATALOG / f"{year}-{month}-{day}.txt", 'a') as f:
                f.writelines(json.dumps(json_data) + '\n')
                f.close()
            return "{'val':'success'}"
        else:
            return "{'val':'failed'}"
    except BaseException as e:
        logger.error(e)
        return "Error has occured."


# 远程浇水控制器查询是否需要浇水
@app.route('/water', methods=['POST'])
def water():
    global waterctl_stat, needwater
    waterctl_stat = request.get_data(as_text=True)
    if waterctl_stat[0] == '2': # 浇水完成
        needwater = '00'
    if waterctl_stat[0] == '1' and needwater == '00': # 手动启动浇水
        needwater = '10'
    wtd.reschedule("interval", seconds=WATERCTL_WTD_TIME)

    return needwater


# 机器人向服务器发送浇水命令
@app.route('/tasks', methods=['POST'])
def taskmanage():
    global needwater
    data = request.get_data(as_text=True)
    if needwater == '00' and data == '20': # 如果当前没有浇水任务等待接受，并且浇水器也不在工作
        return "0"
    else:
        needwater = data
        return "1"


# 向机器人返回浇水控制器工作状态
@app.route('/stat', methods=['GET'])
def report_waterctl_stat():
    return str(waterctl_stat)

def no_flask_logs():
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    def secho(text, file=None, nl=None, err=None, color=None, **styles):
        pass

    def echo(text, file=None, nl=None, err=None, color=None, **styles):
        pass

    click.echo = echo
    click.secho = secho


if __name__ == '__main__':
    no_flask_logs()
    scheduler.start()
    app.run(host=HOST, port=PORT, debug=False)
