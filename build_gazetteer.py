#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建地名库 data/gazetteer.json

组成：
  1. 国家（250）—— 来自 world-countries 数据集：英文名/官方名/中文名/异体拼写/属格形式/经纬度/首都
  2. 首都（250）—— Open-Meteo 地理编码取经纬度
  3. 主要城市与热点地区（策展清单）—— Open-Meteo 地理编码取经纬度
  4. 区域质心 —— 按国家集合聚合，用于区域源兜底

只用标准库 + 一次性的 Open-Meteo 调用（结果缓存进 data/_geocode_cache.json，可重复运行）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
VENDOR = os.path.join(ROOT, "vendor")
GEO_CACHE = os.path.join(DATA, "_geocode_cache.json")
OUT = os.path.join(DATA, "gazetteer.json")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
UA = "news-world-map/1.0 (gazetteer builder)"

# --------------------------------------------------------------------------
# 策展城市清单： "英文名|中文名|国家码(CC2)|别名(逗号分隔)"
# --------------------------------------------------------------------------
CITY_LIST = """
New York|纽约|US|New York City, NYC
Philadelphia|费城|US|Philadelphia PA
Washington|华盛顿|US|Washington DC, Washington D.C.
Los Angeles|洛杉矶|US|LA
Chicago|芝加哥|US|
Houston|休斯敦|US|Houston TX
Phoenix|菲尼克斯|US|
Philadelphia|费城|US|
San Antonio|圣安东尼奥|US|
San Diego|圣迭戈|US|
Dallas|达拉斯|US|
San Jose|圣何塞|US|
Austin|奥斯汀|US|
Jacksonville|杰克逊维尔|US|
Fort Worth|沃思堡|US|
Columbus|哥伦布市|US|
Charlotte|夏洛特|US|
Indianapolis|印第安纳波利斯|US|
San Francisco|旧金山|US|SF, San Fran
Seattle|西雅图|US|
Denver|丹佛|US|
Boston|波士顿|US|
Nashville|纳什维尔|US|
Portland|波特兰|US|
Las Vegas|拉斯维加斯|US|Las Vegas NV
Detroit|底特律|US|
Memphis|孟菲斯|US|
Baltimore|巴尔的摩|US|
Milwaukee|密尔沃基|US|
Albuquerque|阿尔伯克基|US|
Tucson|图森|US|
Sacramento|萨克拉门托|US|
Kansas City|堪萨斯城|US|
Atlanta|亚特兰大|US|
Miami|迈阿密|US|Miami FL
Minneapolis|明尼阿波利斯|US|
New Orleans|新奥尔良|US|
Cleveland|克利夫兰|US|
Salt Lake City|盐湖城|US|
St. Louis|圣路易斯|US|Saint Louis
Pittsburgh|匹兹堡|US|
Cincinnati|辛辛那提|US|
St. Petersburg|圣彼得堡|US|Saint Petersburg FL
Orlando|奥兰多|US|
Tampa|坦帕|US|
Cleveland|克利夫兰|US|
Honolulu|檀香山|US|
Anchorage|安克雷奇|US|
Beijing|北京|CN|Peking
Shanghai|上海|CN|
Guangzhou|广州|CN|Canton
Shenzhen|深圳|CN|
Chengdu|成都|CN|
Chongqing|重庆|CN|
Wuhan|武汉|CN|
Xian|西安|CN|Xi'an
Hangzhou|杭州|CN|
Nanjing|南京|CN|
Tianjin|天津|CN|
Shenyang|沈阳|CN|
Qingdao|青岛|CN|
Changsha|长沙|CN|
Zhengzhou|郑州|CN|
Kunming|昆明|CN|
Harbin|哈尔滨|CN|
Jinan|济南|CN|
Hefei|合肥|CN|
Fuzhou|福州|CN|
Xiamen|厦门|CN|
Urumqi|乌鲁木齐|CN|
Lhasa|拉萨|CN|
Hong Kong|香港|HK|
Macau|澳门|MO|
Taipei|台北|TW|
Tokyo|东京|JP|Tokyo Japan
Osaka|大阪|JP|
Kyoto|京都|JP|
Yokohama|横滨|JP|
Nagoya|名古屋|JP|
Fukuoka|福冈|JP|
Sapporo|札幌|JP|
Seoul|首尔|KR|Seoul South Korea
Pyongyang|平壤|KP|
Busan|釜山|KR|
New Delhi|新德里|IN|Delhi
Mumbai|孟买|IN|Bombay
Kolkata|加尔各答|IN|Calcutta
Bengaluru|班加罗尔|IN|Bangalore
Chennai|钦奈|IN|Madras
Hyderabad|海得拉巴|IN|
Ahmedabad|艾哈迈达巴德|IN|
Jaipur|斋浦尔|IN|
Lucknow|勒克瑙|IN|
Pune|浦那|IN|Poona
Surat|苏拉特|IN|
Kanpur|坎伯尔|IN|
Nagpur|那格浦尔|IN|
Islamabad|伊斯兰堡|PK|
Karachi|卡拉奇|PK|
Lahore|拉合尔|PK|
Peshawar|白沙瓦|PK|
Quetta|奎达|PK|
Dhaka|达卡|BD|
Chittagong|吉大港|BD|
Kathmandu|加德满都|NP|
Colombo|科伦坡|LK|
Kabul|喀布尔|AF|
Kandahar|坎大哈|AF|
Herat|赫拉特|AF|
Tehran|德黑兰|IR|
Esfahan|伊斯法罕|IR|Ispahan
Shiraz|设拉子|IR|
Mashhad|马什哈德|IR|
Tabriz|大不里士|IR|
Baghdad|巴格达|IQ|
Basra|巴士拉|IQ|
Mosul|摩苏尔|IQ|
Kirkuk|基尔库克|IQ|
Erbil|埃尔比勒|IQ|
Damascus|大马士革|SY|
Aleppo|阿勒颇|SY|
Homs|霍姆斯|SY|
Idlib|伊德利卜|SY|
Latakia|拉塔基亚|SY|
Beirut|贝鲁特|LB|
Tripoli|的黎波里|LB|Tripoli Lebanon
Tel Aviv|特拉维夫|IL|
Haifa|海法|IL|
Jerusalem|耶路撒冷|IL|Jerusalem Israel
Gaza|加沙|PS|Gaza City, Gaza Strip
Ramallah|拉姆安拉|PS|
Rafah|拉法|PS|
Khan Yunis|汗尤尼斯|PS|Khan Younis
Beersheba|贝尔谢巴|IL|
Amman|安曼|JO|
Riyadh|利雅得|SA|
Jeddah|吉达|SA|
Mecca|麦加|SA|
Doha|多哈|QA|
Dubai|迪拜|AE|
Abu Dhabi|阿布扎比|AE|
Muscat|马斯喀特|OM|
Kuwait City|科威特城|KW|
Manama|麦纳麦|BH|
Sanaa|萨那|YE|
Aden|亚丁|YE|
Hodeidah|荷台达|YE|
Istanbul|伊斯坦布尔|TR|
Ankara|安卡拉|TR|
Izmir|伊兹密尔|TR|
Antalya|安塔利亚|TR|
Athens|雅典|GR|
Thessaloniki|塞萨洛尼基|GR|
Cairo|开罗|EG|
Alexandria|亚历山大|EG|Alexandria Egypt
Suez|苏伊士|EG|
Tripoli|的黎波里|LY|Tripoli Libya
Benghazi|班加西|LY|
Tunis|突尼斯城|TN|Tunis Tunisia
Sfax|斯法克斯|TN|
Algiers|阿尔及尔|DZ|
Oran|奥兰|DZ|
Rabat|拉巴特|MA|
Casablanca|卡萨布卡|MA|Casablanca Morocco
Marrakesh|马拉喀什|MA|Marrakech
Tangier|丹吉尔|MA|
Khartoum|喀土穆|SD|
Juba|朱巴|SS|
Addis Ababa|亚的斯亚贝巴|ET|
Mogadishu|摩加迪沙|SO|
Nairobi|内罗毕|KE|
Kampala|坎帕拉|UG|
Dar es Salaam|达累斯萨拉姆|TZ|
Kinshasa|金沙萨|CD|
Brazzaville|布拉柴维尔|CG|
Abuja|阿布贾|NG|
Lagos|拉各斯|NG|
Kano|卡诺|NG|
Ibadan|伊巴丹|NG|
Accra|阿克拉|GH|
Dakar|达喀尔|SN|
Bamako|巴马科|ML|
Niamey|尼亚美|NE|
N'Djamena|恩贾梅纳|TD|Ndjamena
Ouagadougou|瓦加杜古|BF|
Conakry|科纳克里|GN|
Freetown|弗里敦|SL|
Monrovia|蒙罗维亚|LR|
Lusaka|卢萨卡|ZM|
Harare|哈拉雷|ZW|
Gaborone|哈博罗内|BW|
Windhoek|温得和克|NA|
Pretoria|比勒陀利亚|ZA|Pretoria South Africa
Cape Town|开普敦|ZA|
Johannesburg|约翰内斯堡|ZA|
Durban|德班|ZA|
Maputo|马普托|MZ|
Luanda|罗安达|AO|
Antananarivo|塔那那利佛|MG|
Victoria|维多利亚|SC|Victoria Seychelles
Port Louis|路易港|MU|
Moroni|莫罗尼|KM|
Dodoma|多多马|TZ|
Asmara|阿斯马拉|ER|
Nouakchott|努瓦克肖特|MR|
Banjul|班珠尔|GM|
Conakry|科纳克里|GN|
Kigali|基加利|RW|
Bujumbura|布琼布拉|BI|
Maseru|马塞卢|LS|
Mbabane|姆巴巴内|SZ|
Lilongwe|利隆圭|MW|
Blantyre|布兰太尔|MW|
Kigali|基加利|RW|
London|伦敦|GB|London UK
Manchester|曼彻斯特|GB|
Birmingham|伯明翰|GB|
Edinburgh|爱丁堡|GB|
Glasgow|格拉斯哥|GB|
Liverpool|利物浦|GB|
Leeds|利兹|GB|
Bristol|布里斯托尔|GB|
Cardiff|卡迪夫|GB|
Belfast|贝尔法斯特|GB|
Dublin|都柏林|IE|
Paris|巴黎|FR|
Marseille|马赛|FR|
Lyon|里昂|FR|
Toulouse|图卢兹|FR|
Nice|尼斯|FR|
Bordeaux|波尔多|FR|
Berlin|柏林|DE|
Munich|慕尼黑|DE|Munich Germany
Hamburg|汉堡|DE|
Frankfurt|法兰克福|DE|
Cologne|科隆|DE|
Dusseldorf|杜塞尔多夫|DE|
Stuttgart|斯图加特|DE|
Leipzig|莱比锡|DE|
Madrid|马德里|ES|
Barcelona|巴塞罗那|ES|
Valencia|瓦伦西亚|ES|
Seville|塞维利亚|ES|
Bilbao|毕尔巴鄂|ES|
Rome|罗马|IT|
Milan|米兰|IT|
Naples|那不勒斯|IT|
Turin|都灵|IT|
Palermo|巴勒莫|IT|
Venice|威尼斯|IT|
Florence|佛罗伦萨|IT|
Genova|热那亚|IT|
Vienna|维也纳|AT|
Salzburg|萨尔茨堡|AT|
Prague|布拉格|CZ|
Brno|布尔诺|CZ|
Budapest|布达佩斯|HU|
Warsaw|华沙|PL|
Krakow|克拉科夫|PL|Kraków
Gdansk|格但斯克|PL|Gdańsk
Wroclaw|弗罗茨瓦夫|PL|Wrocław
Bucharest|布加勒斯特|RO|
Cluj-Napoca|克卢日|RO|
Sofia|索非亚|BG|
Belgrade|贝尔格莱德|RS|
Zagreb|萨格勒布|HR|
Ljubljana|卢布尔雅那|SI|
Sarajevo|萨拉热窝|BA|
Skopje|斯科普里|MK|Tetovo
Tirana|地拉那|AL|
Podgorica|波德戈里察|ME|
Chisinau|基希讷乌|MD|Kishinev
Kyiv|基辅|UA|Kiev, Kyiv Ukraine
Kharkiv|哈尔科夫|UA|Kharkov
Odesa|敖德萨|UA|Odessa
Dnipro|第聂伯罗|UA|Dnipropetrovsk
Zaporizhzhia|扎波罗热|UA|Zaporizhzhia
Mariupol|马里乌波尔|UA|
Lviv|利沃夫|UA|Lvov
Minsk|明斯克|BY|
Moscow|莫斯科|RU|
Saint Petersburg|圣彼得堡|RU|St Petersburg Russia
Volgograd|伏尔加格勒|RU|
Kazan|喀山|RU|
Yekaterinburg|叶卡捷琳堡|RU|
Novorossiysk|新罗西斯克|RU|
Murmansk|摩尔曼斯克|RU|
Sochi|索契|RU|
Kaliningrad|加里宁格勒|RU|
Stockholm|斯德哥尔摩|SE|
Gothenburg|哥德堡|SE|
Oslo|奥斯陆|NO|
Bergen|卑尔根|NO|
Copenhagen|哥本哈根|DK|
Helsinki|赫尔辛基|FI|
Reykjavik|雷克雅未克|IS|
Amsterdam|阿姆斯特丹|NL|
Rotterdam|鹿特丹|NL|
The Hague|海牙|NL|Hague
Brussels|布鲁塞尔|BE|
Antwerp|安特卫普|BE|
Luxembourg|卢森堡|LU|
Zurich|苏黎世|CH|Zurich Switzerland
Geneva|日内瓦|CH|Geneva Switzerland
Bern|伯尔尼|CH|
Basel|巴塞尔|CH|
Lisbon|里斯本|PT|
Porto|波尔图|PT|
Madrid|马德里|ES|
Tallinn|塔林|EE|
Riga|里加|LV|
Vilnius|维尔纽斯|LT|
Toronto|多伦多|CA|
Montreal|蒙特利尔|CA|Montréal
Vancouver|温哥华|CA|
Calgary|卡尔加里|CA|
Ottawa|渥太华|CA|
Edmonton|埃德蒙顿|CA|
Quebec City|魁北克城|CA|Québec
Winnipeg|温尼伯|CA|
Halifax|哈利法克斯|CA|
Mexico City|墨西哥城|MX|Mexico City Mexico
Guadalajara|瓜达拉哈拉|MX|
Monterrey|蒙特雷|MX|
Tijuana|蒂华纳|MX|
Cancun|坎昆|MX|Cancún
Havana|哈瓦那|CU|Havana Cuba
Kingston|金斯敦|JM|Kingston Jamaica
Port-au-Prince|太子港|HT|
Santo Domingo|圣多明各|DO|
Bogota|波哥大|CO|Bogotá
Medellin|麦德林|CO|Medellín
Cartagena|卡塔赫纳|CO|
Caracas|加拉加斯|VE|
Quito|基多|EC|
Guayaquil|瓜亚基尔|EC|
La Paz|拉巴斯|BO|
Santa Cruz|圣克鲁斯|BO|
Asuncion|亚松森|PY|Asunción
Lima|利马|PE|
Arequipa|阿雷基帕|PE|
Santiago|圣地亚哥|CL|Chile Santiago
Valparaiso|瓦尔帕莱索|CL|
Montevideo|蒙得维的亚|UY|
Buenos Aires|布宜诺斯艾利斯|AR|Buenos Aires Argentina
Cordoba|科尔多瓦|AR|Córdoba Argentina
Mendoza|门多萨|AR|
Sao Paulo|圣保罗|BR|São Paulo
Rio de Janeiro|里约热内卢|BR|Rio Brazil
Brasilia|巴西利亚|BR|Brasília
Belo Horizonte|贝洛奥里藏特|BR|
Salvador|萨尔瓦多|BR|
Recife|累西腓|BR|
Fortaleza|福塔莱萨|BR|
Porto Alegre|阿雷格里港|BR|
Manaus|马瑙斯|BR|
Sydney|悉尼|AU|
Melbourne|墨尔本|AU|
Brisbane|布里斯班|AU|
Perth|珀斯|AU|
Adelaide|阿德莱德|AU|
Canberra|堪培拉|AU|
Hobart|霍巴特|AU|
Darwin|达尔文|AU|
Auckland|奥克兰|NZ|
Wellington|惠灵顿|NZ|
Christchurch|基督城|NZ|
Suva|苏瓦|FJ|
Port Moresby|莫尔兹比港|PG|
Honiara|霍尼亚拉|SB|
Apia|阿皮亚|WS|
Noumea|努美阿|NC|
Papeete|帕皮提|PF|
Nukualofa|努库阿洛法|TO|
Majuro|马朱罗|MH|
Tarawa|塔拉瓦|KI|
Funafuti|富纳富提|TV|
Ngerulmud|恩吉鲁穆德|MH|
Mamoudzou|马穆楚|MY|
Port Louis|路易港|MU|
Victoria|维多利亚|SC|
Stanley|斯坦利|FK|
Nuuk|努克|GL|
Iqaluit|伊魁特|CA|
"""

# 热点地区（人工给定经纬度，不走地理编码）
HOTSPOTS = [
    ("Sahel", "萨赫勒", 14.5, 0.0, ["sahel", "sahel region"]),
    ("Horn of Africa", "非洲之角", 8.0, 48.0, ["horn of africa"]),
    ("Balkans", "巴尔干", 44.0, 21.0, ["balkans", "balkan"]),
    ("Gulf States", "海湾国家", 26.0, 50.0, ["gulf states", "gulf region"]),
    ("Scandinavia", "斯堪的纳维亚", 62.0, 15.0, ["scandinavia", "nordic countries"]),
    ("Southeast Asia", "东南亚", 12.0, 105.0, ["southeast asia", "asean"]),
    ("Central Asia", "中亚", 43.0, 65.0, ["central asia"]),
    ("South Asia", "南亚", 22.0, 79.0, ["south asia"]),
    ("East Asia", "东亚", 36.0, 125.0, ["east asia"]),
    ("Central America", "中美洲", 14.5, -89.0, ["central america"]),
    ("Caribbean", "加勒比地区", 18.0, -73.0, ["caribbean"]),
    ("Nuku'alofa", "努库阿洛法", -21.14, -175.2, ["nukualofa", "nuku'alofa"]),
    ("Majuro", "马朱罗", 7.09, 171.38, ["majuro"]),
    ("Mamoudzou", "马穆楚", -12.78, 45.22, ["mamoudzou"]),
    ("West Africa", "西非", 9.0, -3.0, ["west africa"]),
    ("East Africa", "东非", -1.0, 36.0, ["east africa"]),
    ("North Africa", "北非", 28.0, 15.0, ["north africa"]),
    ("Kashmir", "克什米尔", 34.08, 74.8, ["kashmir"]),
    ("Nagorno-Karabakh", "纳戈尔诺-卡拉巴赫", 39.82, 46.75, ["nagorno-karabakh", "karabakh"]),
    ("Xinjiang", "新疆", 43.8, 87.6, ["xinjiang"]),
    ("Tibet", "西藏", 29.6, 91.1, ["tibet"]),
    ("Sinai Peninsula", "西奈半岛", 30.6, 33.6, ["sinai"]),
    ("Sudan's Darfur", "达尔富尔", 13.0, 24.5, ["darfur"]),
    ("Tigray", "提格雷", 13.5, 39.0, ["tigray"]),
    ("Donbas", "顿巴斯", 48.0, 37.5, ["donbas", "donbass"]),
    ("Gaza Strip", "加沙地带", 31.5, 34.47, ["gaza strip"]),
    ("West Bank", "约旦河西岸", 31.95, 35.2, ["west bank", "palestinian territories"]),
    ("Crimea", "克里米亚", 45.3, 34.4, ["crimea", "crimean peninsula"]),
    ("Rohingya", "若开", 20.1, 92.9, ["rohingya"]),
    ("Balochistan", "俾路支", 29.0, 66.0, ["balochistan"]),
    ("Punjab", "旁遮普", 31.0, 75.0, ["punjab"]),
]

# 美国州（含 centroid 近似值）——用于消解 Georgia/Texas/Florida 等州名歧义
US_STATES = [
    ("Alabama", "阿拉巴马州", 32.8, -86.8), ("Alaska", "阿拉斯加州", 64.2, -149.5),
    ("Arizona", "亚利桑那州", 34.3, -111.7), ("Arkansas", "阿肯色州", 34.9, -92.4),
    ("California", "加利福尼亚州", 37.2, -119.5), ("Colorado", "科罗拉多州", 39.0, -105.5),
    ("Connecticut", "康涅狄格州", 41.6, -72.7), ("Delaware", "特拉华州", 39.0, -75.4),
    ("Florida", "佛罗里达州", 28.6, -82.4), ("Georgia", "佐治亚州", 32.6, -83.4),
    ("Hawaii", "夏威夷州", 20.8, -156.3), ("Idaho", "爱达荷州", 44.1, -114.6),
    ("Illinois", "伊利诺伊州", 40.0, -89.2), ("Indiana", "印第安纳州", 39.9, -86.3),
    ("Iowa", "爱荷华州", 42.1, -93.5), ("Kansas", "堪萨斯州", 38.5, -98.4),
    ("Kentucky", "肯塔基州", 37.5, -85.3), ("Louisiana", "路易斯安那州", 31.0, -92.0),
    ("Maine", "缅因州", 45.3, -69.2), ("Maryland", "马里兰州", 39.0, -76.7),
    ("Massachusetts", "马萨诸塞州", 42.3, -71.8), ("Michigan", "密歇根州", 44.3, -85.6),
    ("Minnesota", "明尼苏达州", 46.3, -94.3), ("Mississippi", "密西西比州", 32.7, -89.7),
    ("Missouri", "密苏里州", 38.5, -92.5), ("Montana", "蒙大拿州", 47.0, -109.6),
    ("Nebraska", "内布拉斯加州", 41.5, -99.8), ("Nevada", "内华达州", 39.3, -116.6),
    ("New Hampshire", "新罕布什尔州", 43.7, -71.6), ("New Jersey", "新泽西州", 40.1, -74.5),
    ("New Mexico", "新墨西哥州", 34.4, -106.1), ("New York", "纽约州", 43.0, -75.0),
    ("North Carolina", "北卡罗来纳州", 35.5, -79.4), ("North Dakota", "北达科他州", 47.5, -100.5),
    ("Ohio", "俄亥俄州", 40.3, -82.8), ("Oklahoma", "俄克拉荷马州", 35.5, -97.5),
    ("Oregon", "俄勒冈州", 43.9, -120.6), ("Pennsylvania", "宾夕法尼亚州", 40.9, -77.8),
    ("Rhode Island", "罗得岛州", 41.7, -71.6), ("South Carolina", "南卡罗来纳州", 33.9, -80.9),
    ("South Dakota", "南达科他州", 44.4, -100.2), ("Tennessee", "田纳西州", 35.8, -86.3),
    ("Texas", "得克萨斯州", 31.5, -99.3), ("Utah", "犹他州", 39.3, -111.7),
    ("Vermont", "佛蒙特州", 44.0, -72.7), ("Virginia", "弗吉尼亚州", 37.5, -78.7),
    ("Washington", "华盛顿州", 47.4, -120.7), ("West Virginia", "西弗吉尼亚州", 38.6, -80.6),
    ("Wisconsin", "威斯康星州", 44.6, -89.7), ("Wyoming", "怀俄明州", 43.0, -107.5),
    ("District of Columbia", "华盛顿特区", 38.9, -77.0),
]

# 洲 / 大区（最低置信度，用于「欧洲航线」「亚洲市场」这类泛指）
CONTINENTS = [
    ("Europe", "欧洲", 50.0, 15.0, ["europe", "european", "europeans", "eu", "european union"]),
    ("Asia", "亚洲", 35.0, 90.0, ["asia", "asian", "asians"]),
    ("Africa", "非洲", 2.0, 20.0, ["africa", "african", "africans"]),
    ("North America", "北美洲", 45.0, -100.0, ["north america", "north american", "north americans"]),
    ("South America", "南美洲", -15.0, -60.0, ["south america", "south american", "south americans", "latin america", "latin american"]),
    ("Oceania", "大洋洲", -25.0, 140.0, ["oceania", "oceanian", "pacific islands"]),
    ("Middle East", "中东", 29.0, 45.0, ["middle east", "middle eastern", "mideast"]),
    ("Americas", "美洲", 15.0, -80.0, ["americas", "the americas"]),
]

# 源所属国家（兜底用）
SOURCE_COUNTRY = {
    "npr_world": "US", "npr_us": "US", "cbs_world": "US", "cbs_us": "US",
    "sky_world": "GB", "un_all": "UN", "un_asia": "UN", "un_europe": "UN",
    "f24_main": "FR", "f24_africa": "FR", "f24_asia": "FR", "f24_americas": "FR",
    "f24_me": "FR", "f24_europe": "FR", "abc_intl": "US",
}

# 区域源 → 区域质心
FEED_REGION = {
    "un_asia": "Asia / Pacific", "f24_africa": "Africa", "f24_asia": "Asia / Pacific",
    "f24_americas": "Americas", "f24_me": "Middle East", "f24_europe": "Europe",
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def setup_console():
    """保留控制台原生编码，但无法编码的字符降级为 '?'，避免 Windows GBK 下崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding=stream.encoding or "utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def load_cache():
    if os.path.exists(GEO_CACHE):
        with open(GEO_CACHE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(GEO_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)


def geocode(name, cache, tries=3):
    """Open-Meteo 地理编码；返回 {lat,lon,country,cc,admin1,feature_code,population} 或 None"""
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    url = GEOCODE_URL + "?" + urllib.parse.urlencode(
        {"name": name, "count": 8, "language": "en", "format": "json"}
    )
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8"))
            results = data.get("results") or []
            if not results:
                cache[key] = None
                return None
            # 优先 PCLI（国家）/ PPLC（首都）/ PPLA（一级行政区），否则取人口最高的
            def rank(x):
                fc = x.get("feature_code", "")
                pri = {"PCLI": 0, "PPLC": 1, "PPLA": 2}.get(fc, 3)
                return (pri, -(x.get("population") or 0))

            best = sorted(results, key=rank)[0]
            hit = {
                "lat": round(best["latitude"], 4),
                "lon": round(best["longitude"], 4),
                "country": best.get("country", ""),
                "cc": best.get("country_code", ""),
                "admin1": best.get("admin1", ""),
                "feature_code": best.get("feature_code", ""),
                "population": best.get("population"),
                "matched_name": best.get("name", ""),
            }
            cache[key] = hit
            return hit
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1:
                log(f"    ! geocode failed {name!r}: {e}")
                cache[key] = None
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def resolve_place(name, want_cc, cc2name, cache):
    """
    解析地名并按目标国家消歧。

    地理编码器对重名地名的处理不稳定（费城→巴拉圭、的黎波里→利比亚），
    因此当解析结果的国家与预期不符时，用「地名, 国家名」再查一次。
    """
    hit = geocode(name, cache)
    if not hit or not want_cc:
        return hit
    got = (hit.get("cc") or "").upper()
    if got == want_cc.upper():
        return hit
    country_name = cc2name.get(want_cc.upper())
    if not country_name:
        return hit
    retry = geocode(f"{name}, {country_name}", cache)
    if retry and (retry.get("cc") or "").upper() == want_cc.upper():
        log(f"    ~ disambiguated {name!r}: {hit.get('country')} -> {retry.get('country')}")
        return retry
    log(f"    ! could not disambiguate {name!r} (want {want_cc}, got {got})")
    return hit


def main():
    setup_console()
    os.makedirs(DATA, exist_ok=True)
    cache = load_cache()
    cache_before = len(cache)

    # ---------- 国家 ----------
    wc_path = os.path.join(VENDOR, "world-countries.json")
    if not os.path.exists(wc_path):
        os.makedirs(VENDOR, exist_ok=True)
        url = "https://cdn.jsdelivr.net/npm/world-countries@5.1.0/countries.json"
        log(f"    下载国家数据集 {url}")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        with open(wc_path, "wb") as f:
            f.write(raw)
    with open(wc_path, encoding="utf-8") as f:
        wc = json.load(f)

    countries = []
    for c in wc:
        name = c["name"]["common"]
        official = c["name"]["official"]
        zh = (c.get("translations", {}).get("zho") or {}).get("common", "")
        cc = c["cca2"]
        latlng = c.get("latlng") or [None, None]
        aliases = set()
        aliases.add(name.lower())
        aliases.add(official.lower())
        if zh:
            aliases.add(zh)
        for a in c.get("altSpellings", []) or []:
            if isinstance(a, str) and 2 < len(a) < 40:
                aliases.add(a.lower())
        dem = (c.get("demonyms", {}).get("eng") or {}).get("m")
        if dem:
            aliases.add(dem.lower())        # 常见简称
        extra = {
            "United States": ["us", "u.s.", "usa", "u.s.a.", "america", "american", "united states of america"],
            "United Kingdom": ["uk", "u.k.", "britain", "great britain", "british"],
            "Russia": ["russian federation"],
            "South Korea": ["south korean", "republic of korea", "korea"],
            "North Korea": ["north korean", "dprk", "democratic people's republic of korea"],
            "UAE": ["uae", "u.a.e."],
            "DR Congo": ["drc", "democratic republic of congo", "dr congo"],
            "Czechia": ["czech republic"],
            "Bosnia and Herzegovina": ["bosnia"],
            "Dominican Republic": ["dominican"],
            "Ivory Coast": ["cote d'ivoire", "côte d'ivoire"],
            "Palestine": ["palestinian", "palestinian territories", "state of palestine"],
        }.get(name, [])
        for e in extra:
            aliases.add(e.lower())
        dem_en = (c.get("demonyms", {}).get("eng") or {}).get("m") or ""
        countries.append({
            "name": name, "official": official, "zh": zh, "cc": cc,
            "demonym_en": dem_en,
            "lat": latlng[0] if len(latlng) > 0 else None,
            "lon": latlng[1] if len(latlng) > 1 else None,
            "capital": (c.get("capital") or [None])[0],
            "aliases": sorted(a for a in aliases if a),
        })
    log(f"[1/4] countries: {len(countries)}")

    # ---------- 首都 + 策展城市 地理编码 ----------
    capital_names = sorted({c["capital"] for c in countries if c.get("capital")})
    city_rows = []
    for line in CITY_LIST.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        en = parts[0].strip()
        zh = parts[1].strip() if len(parts) > 1 else ""
        cc = parts[2].strip() if len(parts) > 2 else ""
        aliases = [p.strip() for p in parts[3].split(",") if p.strip()] if len(parts) > 3 else []
        city_rows.append({"name": en, "zh": zh, "cc": cc, "aliases": aliases})

    todo = list(dict.fromkeys(capital_names + [c["name"] for c in city_rows]))
    log(f"[2/4] geocoding {len(todo)} place names (cache has {cache_before}) ...")
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(geocode, n, cache): n for n in todo}
        for fut in futures:
            pass
        for fut, name in futures.items():
            fut.result()
            done += 1
            if done % 50 == 0:
                log(f"    {done}/{len(todo)}")
    save_cache(cache)
    log(f"    geocoded. cache size={len(cache)}")

    # ---------- 组装城市表 ----------
    cities = []
    seen = set()
    cc2name = {c["cc"].upper(): c["name"] for c in countries}
    for row in city_rows:
        hit = resolve_place(row["name"], row["cc"], cc2name, cache)
        if not hit:
            log(f"    ! no geo for city {row['name']!r} -> skipped")
            continue
        key = (row["name"].lower(), row["cc"])
        if key in seen:
            continue
        seen.add(key)
        aliases = {row["name"].lower(), (row["zh"] or "").lower()}
        aliases.update(a.lower() for a in row["aliases"])
        # 注意：不要把 admin1（如 "Pennsylvania"）加进城市别名，
        # 否则州名新闻会被钉到该州某座城市上。州名由 us_states 层单独处理。
        cities.append({
            "name": row["name"], "zh": row["zh"], "cc": row["cc"],
            "country": hit.get("country", ""),
            "lat": hit["lat"], "lon": hit["lon"],
            "pop": hit.get("population"),
            "feature": hit.get("feature_code", ""),
            "aliases": sorted(a for a in aliases if a),
        })
    log(f"[3/4] cities resolved: {len(cities)} / {len(city_rows)}")

    # 首都坐标：单独查一次（很多首都可能已在上面查过）
    capitals = []
    for c in countries:
        if not c.get("capital"):
            continue
        hit = resolve_place(c["capital"], c["cc"], cc2name, cache)
        if not hit:
            continue
        capitals.append({
            "name": c["capital"], "cc": c["cc"], "country": c["name"],
            "zh": c["zh"], "lat": hit["lat"], "lon": hit["lon"],
            "feature": hit.get("feature_code", ""),
        })

    hotspots = [
        {"name": en, "zh": zh, "lat": lat, "lon": lon, "aliases": al}
        for en, zh, lat, lon, al in HOTSPOTS
    ]
    us_states = [
        {"name": en, "zh": zh, "lat": lat, "lon": lon,
         "aliases": [en.lower(), zh]}
        for en, zh, lat, lon in US_STATES
    ]
    continents = [
        {"name": en, "zh": zh, "lat": lat, "lon": lon,
         "aliases": [a.lower() for a in al]}
        for en, zh, lat, lon, al in CONTINENTS
    ]

    # ---------- 区域质心 ----------
    groups = {}
    for c in wc:
        key = c.get("subregion") or c.get("region") or "Other"
        groups.setdefault(key, []).append(c.get("latlng") or [])
    region_centroids = {}
    for key, pts in groups.items():
        pts = [p for p in pts if len(p) == 2 and p[0] is not None and p[1] is not None]
        if not pts:
            continue
        region_centroids[key] = [
            round(sum(p[0] for p in pts) / len(pts), 3),
            round(sum(p[1] for p in pts) / len(pts), 3),
        ]
    # 手工补充 France24 / UN 用的区域名
    manual_regions = {
        "Africa": [1.0, 20.0],
        "Asia / Pacific": [25.0, 115.0],
        "Americas": [15.0, -80.0],
        "Middle East": [29.0, 45.0],
        "Europe": [50.0, 15.0],
    }
    region_centroids.update(manual_regions)

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "countries": countries,
        "capitals": capitals,
        "cities": cities,
        "hotspots": hotspots,
        "us_states": us_states,
        "continents": continents,
        "region_centroids": region_centroids,
        "source_country": SOURCE_COUNTRY,
        "feed_region": FEED_REGION,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(OUT)
    log(f"[4/4] wrote {OUT} ({size/1024:.0f} KB)  "
        f"countries={len(countries)} capitals={len(capitals)} cities={len(cities)} hotspots={len(hotspots)}")


if __name__ == "__main__":
    main()
