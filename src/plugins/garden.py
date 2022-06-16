import json
import time
import os
from pathlib import Path
from datetime import datetime
from multiprocessing import Process

import httpx
from apscheduler.jobstores.base import ConflictingIdError, JobLookupError
from nonebot import require, get_driver
from nonebot.adapters.cqhttp import Bot, Event, MessageEvent, GroupMessageEvent
from nonebot.adapters.cqhttp.message import Message
from nonebot.log import logger
from nonebot.plugin import on_command
from nonebot.typing import T_State

CATALOG = Path("./weather_data")  # 本地天气缓存存放文件夹
TARGET_GROUP = 9900000000  # 花园群
WATER_AUTHLIST = ['10000', '10001']
TASK_TIMEOUT_CHECK = 30  # 下发浇水任务后未得到执行的超时时间，单位为秒
WATER_DAEMON_INTERVAL = 5
HTTP_SERVER_IP = "127.0.0.1"
HTTP_SERVER_PORT = "5051"

sch = require('nonebot_plugin_apscheduler').scheduler
status_old = "*"
global_bot = None


## 关于
about = on_command('关于系统')


@about.handle()
async def _about_handler(bot: Bot, event: MessageEvent):
    text = Message(
        "【关于系统】\n我是基于Nonebot2、Flask、ESP8266和阿里云开发的，专用于香农花园的自动灌溉系统。")
    await about.finish(text, at_sender=True)


## 显示菜单
intro = on_command('花园功能')


@intro.handle()
async def _intro_handler(bot: Bot, event: MessageEvent):
    text = Message("☆机器人功能表☆\n")
    text += Message("\n")
    text += Message("注：X代表需要在命令中提供具体参数，缺少时将要求提供。\n")
    text += Message("【天气预报 X】获取由心知天气提供的三日天气预报，X：今天0/明天1/后天2。\n")
    text += Message("【花园浇水 X】下发远程浇水指令，X：0-全区域浇水 1/2/3-指定区域浇水。此命令只能由指定群成员启动。\n")
    text += Message("【取消浇水】取消正在下发或正在进行的浇水任务。此命令只能由指定群成员启动。\n")
    text += Message("【花园天气】获得花园的最新天气状态。数据由位于花园的温湿度传感器提供。\n")
    text += Message("【控制器状态】查询浇水控制器的工作状态。\n")
    text += Message("【花园功能】获得关于机器人的可用命令。\n")
    text += Message("【你好】用于测试机器人是否在线。\n")
    text += Message("【关于系统】获得关于整个自动灌溉系统的简单介绍。\n")

    await intro.finish(text)


async def statcheck():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"http://{HTTP_SERVER_IP}:{HTTP_SERVER_PORT}/stat")
        if r.text != "":
            return r.text
        else:
            raise ValueError('【statcheck】获取控制器状态失败')
    except httpx.RequestError:
        raise ValueError('【statcheck】获取控制器状态失败')


def status_msg_constructor(status_code: str):
    logger.info(f"浇水控制器状态码：{status_code}")
    if status_code[0] == '?':
        return '浇水控制器已离线'
    if status_code[0] == '0':
        return '浇水控制器在线且空闲'
    if status_code[0] == '1':
        return f'正在浇灌第{status_code[1]}区域'
    if status_code[0] == '2':
        return '浇水任务已完成'  


async def waterctl_daemon():
    global status_old
    status = await statcheck()
    if status_old == "*":
        status_old = status
    if status_old != status:
        if not(status_old == "20" and status == "00"):
            await global_bot.send_group_msg(group_id=TARGET_GROUP, message=status_msg_constructor(status))
        status_old = status


## 机器人初始化
driver = get_driver()


@driver.on_bot_connect
async def _bot_init(bot: Bot):
    global global_bot
    global_bot = bot
    logger.info("香农花园机器人已接入")

    if not os.path.exists(CATALOG):
        os.mkdir(CATALOG)
    os.popen("python http_server.py")
    # http_server = Process(target=lambda: os.system("python http_server.py"))
    # http_server.start()
    logger.info("HTTP服务器已启动")

    sch.add_job(waterctl_daemon, "interval", seconds=WATER_DAEMON_INTERVAL, id="waterctl_daemon")
    logger.info("浇水控制器守护进程已启动")


## 问好，可用于测试机器人是否在线
hello = on_command('你好')


@hello.handle()
async def _hello_handler(bot: Bot, event: MessageEvent):
    text = Message("你好")
    await hello.finish(text, at_sender=True)


def sensordata_serialize(dictdata):
    temp = "温度：" + dictdata['temp'] + '°C\n'
    humid = "湿度：" + dictdata['humid'] + '%\n'
    rained = '没有下雨\n' if dictdata['rain'] == '1' else '下雨了\n'
    wet = '相对干燥\n' if dictdata['wet'] == '1' else '潮湿\n'
    updatetime = datetime.fromtimestamp(dictdata['time'])
    return "【花园实时天气】\n" + temp + humid + "是否下雨：" + rained + "土壤潮湿程度：" + wet + "数据更新时间：" + str(updatetime)


def get_sensor_data():
    year = str(time.localtime(time.time()).tm_year)
    month = str(time.localtime(time.time()).tm_mon)
    day = str(time.localtime(time.time()).tm_mday)
    try:
        with open(CATALOG / f"{year}-{month}-{day}.txt", 'rb') as f:
            f.seek(-300, 2)
            lines = f.readlines()
            last_line = lines[-1]
            dictdata = json.loads(last_line)
    except BaseException as e:
        print('错误信息：', e)
        print('文件地址：', CATALOG / f"{year}-{month}-{day}.txt")
        return -1
    return sensordata_serialize(dictdata)


## 定时推送花园天气
# @sch.scheduled_job('cron', hour='8-20/6')  # 在8 14 20点定时推送花园天气信息，不需要定时推送时请注释掉这一行
async def _auto_report_weather():
    weather = get_sensor_data()
    if weather == -1:
        weather = "读取天气信息缓存出错，请检查本地缓存"
    else:
        hrs = time.localtime(time.time()).tm_hour
        if hrs == 8: weather = "早上好~[CQ:face,id=74]" + weather
        if hrs == 14: weather = "下午好~[CQ:face,id=285]" + weather
        if hrs == 20: weather = "晚上好~[CQ:face,id=75]" + weather
    msg = Message(weather)
    await global_bot.send_group_msg(group_id=TARGET_GROUP, message=msg)


## 手动获取最新花园天气
garden_weather = on_command('花园天气')


@garden_weather.handle()
async def _message(bot: Bot, event: MessageEvent):
    weather = get_sensor_data()
    if weather == -1:
        weather = "读取天气信息缓存出错，请检查本地缓存"
    await garden_weather.finish(weather, at_sender=True)


async def get_forcast(day: int) -> str:
    try:
        urlstr2 = "https://api.seniverse.com/v3/weather/daily.json?" + "key=Sgm9GqFGZhZZXQTiL" + "&location=30.758062:103.937054" + "&language=zh-Hans&unit=c&start=0&days=3"
        async with httpx.AsyncClient() as client:
            rsps = await client.get(urlstr2)
        load = json.loads(rsps.text)
        datetime.fromisoformat
        data = load['results'][0]['daily'][day]
        updatetime = load['results'][0]['last_update']
        updatetime = datetime.fromisoformat(updatetime)
        ret = "【天气预报】\n日期：" + data['date'] + "\n日间天气：" + data['text_day'] + "\n晚间天气：" + data['text_night'] + "\n温度：" + \
              data['low'] + "~" + data['high'] + "°C" + "\n更新时间：" + str(updatetime)
        return ret
    except BaseException as e:
        print('[ERROR] 错误信息：', e)
        return -1


## 定时推送当地天气预报
# @sch.scheduled_job('cron', hour='8')  # 在8点自动推送当地天气预报，不需要定时推送时请注释掉这一行
async def _auto_report_weatherforcast():
    weather = await get_forcast(0)
    if weather == -1:
        weather = "读取天气预报出错，请检查服务器状态"
    await global_bot.send_group_msg(group_id=TARGET_GROUP, message=weather)


## 手动获取当地天气预报
weather_forcast = on_command('天气预报')


@weather_forcast.handle()
async def _wfreceive(bot: Bot, event: MessageEvent, state: T_State):
    arg = str(event.get_message()).strip()
    if arg:
        state['day'] = arg


@weather_forcast.got('day', prompt="你想查询哪一天的天气预报呢？（0-今天 1-明天 2-后天）")
async def _wfreport(bot: Bot, event: MessageEvent, state: T_State):
    day = state['day']
    if day not in ['0', '1', '2']:
        await weather_forcast.reject("错误的日期请求，请重新输入", at_sender=True)
    weather = await get_forcast(int(day))
    if weather == -1:
        weather = "读取天气预报出错，请检查服务器状态"
    await weather_forcast.finish(weather, at_sender=True)


async def water_auth_checker(bot: Bot, event: Event, state: T_State):
    if event.get_user_id() in WATER_AUTHLIST:
        return True
    else:
        return False


async def task_timeout_checker(event: GroupMessageEvent):
    sch.remove_job("water_timeout_check")
    try:
        stat = await statcheck()
        if stat[0] != '1':  # 如果控制器不在浇水
            await global_bot.send_group_msg(group_id=event.group_id, message="下发的浇水任务长时间未得到执行，请检查远端工作状态")
    except BaseException as e:
        logger.error('[ERROR] 错误信息：', e)


async def send_task(task):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(F"http://{HTTP_SERVER_IP}:{HTTP_SERVER_PORT}/tasks", data=task)
        if r.text != "":
            return r.text
        else:
            raise ValueError('【sendtasks】下发任务失败')
    except httpx.RequestError:
        raise ValueError('【sendtasks】下发任务失败')


## 远程启动花园浇水
garden_watering = on_command('花园浇水', rule=water_auth_checker)


@garden_watering.handle()
async def _waterchk(bot: Bot, event: MessageEvent, state: T_State):
    arg = str(event.get_message()).strip()
    try:
        state['stat'] = await statcheck()
        if state['stat'][0] == '1':
            await garden_watering.finish("上一个浇水任务正在进行，无法下发新任务", at_sender=True)
        if state['stat'] == '?':
            await garden_watering.finish("浇水控制器当前离线，无法下发新任务", at_sender=True)
        if arg:
            state['block'] = arg
    except ValueError as e:
        logger.error(e)
        await garden_watering.finish('启动浇水失败', at_sender=True)


@garden_watering.got('block', prompt='请回复浇水区域：\n0 - 全区域\n1/2/3 - 只浇指定区域\nq - 取消')
async def _watering(bot: Bot, event: MessageEvent, state: T_State):
    reply = state['block']
    if reply not in ['0', '1', '2', '3', 'q']:
        await garden_watering.reject('错误的回复方式，请重新输入', at_sender=True)
    if reply == 'q':
        await garden_watering.finish('已取消下发浇水指令', at_sender=True)
    try:
        await send_task('1' + reply)
        sch.add_job(task_timeout_checker, "interval", seconds=TASK_TIMEOUT_CHECK, id='water_timeout_check', args=[event])
        await garden_watering.finish('浇水任务已下发', at_sender=True)
    except ValueError as e:
        logger.error(e)
        await garden_watering.finish('下发任务失败', at_sender=True)
    except ConflictingIdError:
        sch.remove_job("water_timeout_check")
        sch.add_job(task_timeout_checker, "interval", seconds=TASK_TIMEOUT_CHECK, id='water_timeout_check', args=[event])


## 取消尚未执行或正在执行的浇水任务
task_cancel = on_command('取消浇水', rule=water_auth_checker)


@task_cancel.handle()
async def _waterchk(bot: Bot, event: MessageEvent, state: T_State):
    state['qq'] = event.get_user_id()
    try:
        ret = await send_task('20')
        if ret == '0':
            await task_cancel.finish("当前没有正在执行的任务", at_sender=True)
        else:
            try:
                sch.remove_job("water_timeout_check")
            except JobLookupError:
                pass
            await task_cancel.finish("取消任务指令已下发", at_sender=True)
    except ValueError as e:
        logger.error(e)
        await task_cancel.finish('取消任务失败', at_sender=True)


## 检查浇水控制器在线状态
waterctl_chk = on_command('控制器状态')


@waterctl_chk.handle()
async def _waterctl_handler(bot: Bot, event: MessageEvent):
    try:
        r = await statcheck()
        msg = status_msg_constructor(r)
        await garden_watering.finish(msg, at_sender=True)
    except httpx.RequestError:
        msg = '获取浇水控制器状态失败'
        await garden_watering.finish(msg, at_sender=True)
