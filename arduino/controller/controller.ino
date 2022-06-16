#include <ESP8266WiFi.h>
#include <ESP8266WiFiMulti.h>
#include <ArduinoJson.h>
#include <Ticker.h>
#include <AsyncHTTPRequest_Generic.h>

#define MUSICPIN 2

#define BLOCK1 14                           //继电器引脚
#define BLOCK2 12                           //继电器引脚
#define BLOCK3 13                           //继电器引脚
#define BLOCK_NUMS 3                        //总继电器数量
int blocks[] = {0, BLOCK1, BLOCK2, BLOCK3}; //存放着每个继电器引脚的数组，第一个必须为0

#define ON LOW //继电器低电平触发
#define OFF !ON

#define CHECKTIME 5  //浇水任务检查时间（单位为秒）
#define MUSICTIME 60 //音乐播放时间（单位为秒）
int watertime[] = {0, 60 * 1, 60 * 1, 60 * 1}; //每个区域的浇水时间（单位为秒）

int watering = 0; //全局变量：0-空闲 1-正在浇水 2-浇水完成正在上报
int music = 0;    //全局变量：确认是否启动音乐
int nowblock = 0; //当前正在浇水的区域
int connecting = 0; // 当前正在和服务器通信（同一时间仅允许一个通信请求）

const char* SERVER_URL = "http://服务器IP地址:端口/water";

//音乐相关参数，歌曲：《世界真细小》
int scale[] = {0,
               264, 281, 297, 316, 330, 352, 371, 396, 422, 440, 475, 495,
               528, 563, 594, 633, 660, 704, 742, 792, 844, 880, 950, 990,
               1056, 1126, 1188, 1267, 1320, 1408, 1485, 1584, 1689, 1760, 1900, 1980}; //十二平均律
int note[] = {5, 6, 8, 5 + 12, 1 + 12, 3 + 12, 1 + 12, 1 + 12, 12, 12,
              3, 5, 6, 3 + 12, 12, 1 + 12, 12, 10, 8, 8,
              5, 6, 8, 1 + 12, 3 + 12, 5 + 12, 3 + 12, 1 + 12, 10, 3 + 12, 5 + 12, 6 + 12,
              5 + 12, 3 + 12, 8, 6 + 12, 5 + 12, 3 + 12, 1 + 12, 1 + 12,
              1 + 12, 1 + 12, 5 + 12, 1 + 12, 3 + 12, 3 + 12, 3 + 12,
              3 + 12, 3 + 12, 6 + 12, 3 + 12, 5 + 12, 5 + 12, 5 + 12,
              5 + 12, 5 + 12, 8 + 12, 5 + 12, 6 + 12,
              6 + 12, 6 + 12, 5 + 12, 3 + 12, 8, 12, 1 + 12, 1 + 12};
int musictone = +7; // G调
int notedelay[] = {1, 1, 2, 2, 2, 1, 1, 2, 2, 2,
                   1, 1, 2, 2, 2, 1, 1, 2, 2, 2,
                   1, 1, 2, 1, 1, 2, 1, 1, 2, 1, 1, 2,
                   1, 1, 2, 2, 2, 2, 4, 4,
                   3, 1, 2, 2, 3, 1, 4,
                   3, 3, 2, 2, 3, 1, 4,
                   3, 1, 2, 2, 3,
                   1, 2, 1, 1, 4, 4, 4, 2}; //每个音符对应拍数
int musiclen = 67;                          //音乐长度（音符个数）
int spd = 250;                              //四分音符时长

AsyncHTTPRequest request;
Ticker ticker;  // HTTP异步查询、上报时间间隔控制
Ticker ticker1; //浇水时间控制
Ticker ticker2; //按键防抖
ESP8266WiFiMulti wifiMulti;

ICACHE_RAM_ATTR void handleInterrupt()
{ //外部中断设置，用于手动启停WATERTIME时间的浇水
  ticker2.once(0.02, buttonshake);
}

void buttonshake()
{
  if (digitalRead(0) == LOW)
  {
    manualWatering();
  }
}

void wifisetup()
{
  wifiMulti.addAP("", "");
  // wifiMulti.addAP("", "");
  int i = 0;
  while (wifiMulti.run() != WL_CONNECTED)
  {
    delay(1000);
    Serial.print(i++);
    Serial.print(' ');
    if (i > 10)
      ESP.restart();
  }

  Serial.println('\n');
  Serial.print("[Network] Connected to ");
  Serial.println(WiFi.SSID());
  Serial.print("[Network] IP address:\t");
  Serial.println(WiFi.localIP());
  // Serial.println(WiFi.subnetMask());
  // Serial.println(WiFi.gatewayIP());
  // Serial.println(WiFi.macAddress());
}

void relaysetup()
{
  pinMode(BLOCK1, OUTPUT);
  pinMode(BLOCK2, OUTPUT);
  pinMode(BLOCK3, OUTPUT);
  relaycontrol(BLOCK1, OFF);
  relaycontrol(BLOCK2, OFF);
  relaycontrol(BLOCK3, OFF);
}

void relaycontrol(int block, int stat)
{
  digitalWrite(block, stat);
}

//手动启动/停止浇水
void manualWatering()
{
  Serial.println("[Water] Watering Process raised by INTERRUPT!");
  if (watering == 1)
  { //如果已经在浇水了，就关闭浇水
    stopWatering();
    httpRequest();
    Serial.println("[Water] Watering Process has alreadly run, but just now it stopped.");
  }
  if (watering == 0)
  {
    startWatering('0');
    httpRequest();
  }
}

void stopWatering()
{               //停止浇水
  relaysetup(); //重置所有继电器状态
  ticker1.detach();
  nowblock = 0;
  watering = 2;
  music = 0;
  httpRequest();
  Serial.println("[Water] Watering Process is stopped.");
}

/**
 * @brief 启动浇水
 * @param target 指定区域（字符形式）。其中'0'代表全区域，'1''2''3'代表各自区域
 */
void startWatering(char target)
{                              //开始浇水
  nowblock = int(target) - 48; // 字符转数字：'0' -> 0
  if (nowblock == 0)
    relayloop();
  else
    relaysingle();
  music = 1;
  watering = 1;
  Serial.println("[Water] Watering Process is running.");
}

void relayloop()
{ //继电器循环控制
  nowblock++;
  if (nowblock > BLOCK_NUMS)
  {
    stopWatering();
  }
  else
  {
    if (nowblock != 1)
      relaycontrol(blocks[nowblock - 1], OFF);
    relaycontrol(blocks[nowblock], ON);
    Serial.print("[Water] Now watering Block ");
    Serial.println(nowblock);
    ticker1.once(watertime[nowblock], relayloop);
  }
}

void relaysingle()
{ // 继电器单独控制
  relaycontrol(blocks[nowblock], ON);
  Serial.print("[Water] Now watering Block ");
  Serial.println(nowblock);
  ticker1.once(watertime[nowblock], stopWatering);
}

void httpRequest()
{
  static bool requestOpenResult;

  if (!connecting && (request.readyState() == readyStateUnsent || request.readyState() == readyStateDone))
  {
    requestOpenResult = request.open("POST", SERVER_URL);
    if (requestOpenResult)
    {
      // Only send() if open() returns true, or crash
      request.send(String(watering) + String(nowblock)); // 汇报当前工作状态和浇灌区域
      Serial.println("[HTTP] Send watering status:"+String(watering) + String(nowblock));
      connecting = 1;
    }
    else
    {
      Serial.println("[HTTP] Can't send bad request");
    }
  }
  else
  {
    if (connecting)
      Serial.println("[HTTP] Waiting for last request...");
    else
      Serial.println("[HTTP] Can't send request");
  }
}

void requestCB(void *optParm, AsyncHTTPRequest *request, int readyState)
{
  (void)optParm;
  String payload;
  if (readyState == readyStateDone)
  {
    connecting = 0;
    payload = request->responseText();
    Serial.print("[HTTP] Server Response:");
    Serial.println(payload);
    request->setDebug(false);

    if (payload[0] == '2' && watering == 1) // 正在浇水时收到2，立即停止浇水任务
      stopWatering();
    if (payload[0] == '0' && watering == 2) // 报告已完成浇水任务后，watering标识为空闲
      watering = 0;
    if (payload[0] == '1' && watering == 0) // 如果不在浇水，就开始浇水；如果正在浇水，服务器端应当给出提示。
      startWatering(payload[1]);
  }
}

void startmusic()
{
  int i = 0;
  Serial.println("[Music] Music starts.");
  while (music)
  {
    digitalWrite(LED_BUILTIN, LOW); //点亮LED
    if (i >= musiclen)
      i = 0;
    analogWrite(MUSICPIN, 64); // 128/255
    analogWriteFreq(scale[note[i] + musictone]);
    delay(spd * notedelay[i]);
    analogWrite(MUSICPIN, 0);
    delay(25);
    i++;
  }
  analogWrite(MUSICPIN, 0);
  digitalWrite(LED_BUILTIN, HIGH); //熄灭LED
  Serial.println("[Music] Music stops.");
}
void stopmusic()
{
  music = 0;
}

void setup() // 程序入口
{
  Serial.begin(9600);
  Serial.println("");
  relaysetup();                    // 继电器引脚初始化
  pinMode(0, INPUT_PULLUP);        // 按键启动浇水（整块板子除了复位只有一个按键FLASH）
  pinMode(LED_BUILTIN, OUTPUT);    // LED显示阀门状态（整块板子就一个LED）
  digitalWrite(LED_BUILTIN, HIGH); // 初始状态熄灭LED
  wifisetup();
  attachInterrupt(digitalPinToInterrupt(0), handleInterrupt, FALLING); //启动外部按键中断，按下按键时（下降沿）自动浇水
  request.setDebug(false);                                             // 异步HTTP请求初始化
  request.onReadyStateChange(requestCB);
  ticker.attach(CHECKTIME, httpRequest); // 定时查询是否存在浇水请求
}

void loop() // 程序主循环
{
  if (music)
  {
    startmusic();
  }
  delay(1e3);
}
