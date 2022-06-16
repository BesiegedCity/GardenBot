#include <SimpleDHT.h>
#include <ESP8266WiFi.h>
#include <ESP8266WiFiMulti.h>
#include <ArduinoJson.h>
#include <ESP8266HTTPClient.h>

#define DHT11PIN 4 //代表GPIO4
#define RAINPIN 14
#define WETPIN 9//土壤湿度

const static int INTERVAL = 30; // 推送时间间隔，单位分钟
SimpleDHT11 DHT11(DHT11PIN);
 
ESP8266WiFiMulti wifiMulti;           // 建立ESP8266WiFiMulti对象

#define HOST "服务器IP地址"
#define URL "http://" HOST ":服务器端口/upload"// 网络服务器地址 

void setup(){
  Serial.begin(9600);          
  Serial.println("");
  pinMode(RAINPIN,INPUT);
  pinMode(WETPIN,INPUT);

  wifiMulti.addAP("", "");
  // wifiMulti.addAP("", "");

  int i = 0;                                 
  while (wifiMulti.run() != WL_CONNECTED) {
    delay(1000);
    Serial.print(i++); Serial.print(' ');
  } 

  Serial.println('\n');
  Serial.print("Connected to ");
  Serial.println(WiFi.SSID());
  Serial.print("IP address:\t");
  Serial.println(WiFi.localIP());
}
 
void loop(){
  httpRequest();
  delay(6e4*INTERVAL);
}
 
// 向服务器发送HTTP请求，请求信息中包含json信息
void httpRequest(){
  // 建立WiFi客户端对象，对象名称client
  WiFiClient client;    
 
  // 根据jsonType参数建立不同类型JSON
  String payloadJson = buildJson(); 
  
  // 建立字符串，用于HTTP请求
  String httpRequest =  String("POST /upload") + " HTTP/1.1\r\n" +
                        "Host: " HOST "\r\n" +
                        "Content-Type: application/json; charset=utf-8\r\n" +
                        "Connection: close\r\n\r\n";

  HTTPClient httpClient;
 
  //配置请求地址。此处也可以不使用端口号和PATH而单纯的
  httpClient.begin(client, URL); 
 
  //启动连接并发送HTTP请求
  int httpCode = httpClient.POST(payloadJson);
  
  //如果服务器响应OK则从服务器获取响应体信息并通过串口输出
  //如果服务器不响应OK则将服务器响应状态码通过串口输出
    //连接失败时 httpCode时为负
  if (httpCode > 0) {
    //将从服务器获取的数据打印到串口
    if (httpCode == HTTP_CODE_OK) {
      const String& payload = httpClient.getString();
      Serial.print("Received payload: ");
      Serial.println(payload);
    }
  } else {
    Serial.printf("[HTTP] POST... failed, error: %s\n", httpClient.errorToString(httpCode).c_str());
  }
  //关闭http连接
  httpClient.end();
}
//建立json信息
String buildJson(){
  //读取温湿度传感器信息
  byte temperature = 0;
  byte humidity = 0;

  // 开始ArduinoJson Assistant的serialize代码 
  StaticJsonDocument<96> doc;
  DHT11.read(&temperature, &humidity, NULL);

  doc["temp"] = String(temperature);
  doc["humid"] = String(humidity);
  doc["rain"] = String(digitalRead(RAINPIN));
  doc["wet"] = String(digitalRead(WETPIN));
  
  String output;
  serializeJson(doc, output);
  Serial.print("Json Code: ");Serial.println(output); 
   
  return output;
}
