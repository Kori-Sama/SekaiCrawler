from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import asyncio
import os
from asyncio import Queue
from typing import Tuple
import json  # 添加json导入


async def fetch_image_url(url):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--proxy-server=http://127.0.0.1:7890")

    # 使用本地 ChromeDriver
    driver = webdriver.Chrome(
        service=Service("./chromedriver-win64/chromedriver.exe"),
        options=chrome_options,
    )

    try:
        # 访问页面
        driver.get(url)

        # 获取卡片ID从URL
        # card_id = url.split("/")[-1]

        # 等待角色名称元素加载
        wait = WebDriverWait(driver, 10)
        character_name = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//h6[contains(text(), 'Character')]/../..//p[contains(@class, 'MuiTypography-alignRight')]",
                )
            )
        ).text.replace(" ", "")

        print(f"角色: {character_name}")

        # 等待图片元素加载完成
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[style*="background-image"]')
            )
        )

        # 获取特训前的图片
        image_urls = []
        elements = driver.find_elements(By.CSS_SELECTOR, '[style*="background-image"]')
        for element in elements:
            style = element.get_attribute("style")
            if "background-image" in style:
                url_start = style.find('url("') + 5
                url_end = style.find('")', url_start)
                image_url = style[url_start:url_end]
                if image_url:
                    print("特训前的图片", image_url)
                    image_urls.append(("normal", image_url))

        # 点击"特训后卡图"按钮
        trained_tab = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//button[contains(., 'After training image')]")
            )
        )
        trained_tab.click()

        # 等待新图片加载
        await asyncio.sleep(1)  # 给页面一点时间加载

        # 获取特训后的图片
        elements = driver.find_elements(By.CSS_SELECTOR, '[style*="background-image"]')
        for element in elements:
            style = element.get_attribute("style")
            if "background-image" in style:
                url_start = style.find('url("') + 5
                url_end = style.find('")', url_start)
                image_url = style[url_start:url_end]
                if image_url and ("normal", image_url) not in image_urls:
                    print("特训后的图片", image_url)
                    image_urls.append(("trained", image_url))

        return image_urls, character_name

    finally:
        driver.quit()


async def save_to_json(url_info: Tuple, character_name: str, card_id: str):
    """将图片信息保存到JSON文件"""
    status, url = url_info
    data = {
        "character_name": character_name,
        "card_id": card_id,
        "status": status,
        "url": url,
    }

    json_file = "card_images.json"

    try:
        # 读取现有数据
        if os.path.exists(json_file):
            with open(json_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        else:
            existing_data = []

        # 添加新数据
        existing_data.append(data)

        # 保存更新后的数据
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        print(f"已保存卡片 {card_id} 的{status}图片信息")
    except Exception as e:
        print(f"保存JSON数据时出错: {str(e)}")


CARD_TOTAL = 1132


async def producer(queue: Queue, start_id: int, end_id: int):
    """生产者：爬取卡片页面并将下载任务加入队列"""
    for card_id in range(start_id, end_id + 1):
        url = f"https://sekai.best/card/{card_id}"
        try:
            image_urls, character_name = await fetch_image_url(url)
            for url_info in image_urls:
                # 将下载任务信息打包放入队列
                await queue.put((url_info, character_name, str(card_id)))
            print(f"已将卡片 {card_id} 的下载任务加入队列")
        except Exception as e:
            print(f"处理卡片 {card_id} 时出错: {str(e)}")
            continue


async def consumer(queue: Queue):
    """消费者：从队列获取任务并保存信息到JSON"""
    while True:
        try:
            url_info, character_name, card_id = await queue.get()
            await save_to_json(url_info, character_name, card_id)
            queue.task_done()
        except Exception as e:
            print(f"保存任务执行出错: {str(e)}")
            queue.task_done()
            continue


async def main():
    # 创建一个队列来存储下载任务
    queue = Queue()

    # 创建多个消费者
    consumers = [asyncio.create_task(consumer(queue)) for _ in range(5)]

    # 启动生产者
    await producer(queue, 1, CARD_TOTAL)

    # 等待所有任务完成
    await queue.join()

    # 取消所有消费者
    for c in consumers:
        c.cancel()


if __name__ == "__main__":
    # 确保存在 images 目录
    os.makedirs("images", exist_ok=True)
    asyncio.run(main())
