from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import asyncio
import httpx
import os
from asyncio import Queue


async def fetch_image_url(url):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    # chrome_options.add_argument("--proxy-server=http://127.0.0.1:7890")

    # 使用本地 ChromeDriver
    driver = webdriver.Chrome(service=Service(), options=chrome_options)

    try:
        # 访问页面
        driver.get(url)

        # 获取卡片ID从URL
        card_id = url.split("/")[-1]
        print(f"Card ID: {card_id}")

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

        stars = 0
        # 获取卡片星级
        for tmp in driver.find_elements(By.CLASS_NAME, "css-5kc7yo"):
            stars_elm = tmp.find_elements(By.TAG_NAME, "img")
            if stars_elm != []:
                stars = len(stars_elm)

        if stars == 0:
            raise "Fetch stars failed!"

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

        return image_urls, character_name, card_id, stars

    finally:
        driver.quit()


async def download_worker(queue: Queue, client: httpx.AsyncClient):
    while True:
        try:
            # 从队列获取下载任务
            url_info, character_name, card_id, stars = await queue.get()
            status, url = url_info

            # 创建角色专属目录
            character_dir = os.path.join("images", character_name)
            os.makedirs(character_dir, exist_ok=True)

            # 根据stars分目录
            stars_dir = os.path.join(character_dir, f"{stars}星")
            os.makedirs(stars_dir, exist_ok=True)

            # 根据图片状态构建文件名
            prefix = "trained_" if status == "trained" else "normal_"
            filename = f"{prefix}{card_id}.webp"
            filepath = os.path.join(stars_dir, filename)

            try:
                response = await client.get(url)
                if response.status_code == 200:
                    # 保存图片
                    with open(filepath, "wb") as f:
                        f.write(response.content)
                    print(f"成功下载图片: {filepath}")
                else:
                    print(f"下载失败: {url}")
            except Exception as e:
                print(f"下载出错 {url}: {str(e)}")

            queue.task_done()
        except Exception as e:
            print(f"工作进程发生错误: {str(e)}")


async def producer(queue: Queue, start_id: int, end_id: int):
    for card_id in range(start_id, end_id + 1):
        try:
            url = f"https://sekai.best/card/{card_id}"
            image_urls, character_name, _, stars = await fetch_image_url(url)

            print(f"卡片 {card_id}: 找到 {len(image_urls)} 个图片URL")

            # 将下载任务加入队列
            for url_info in image_urls:
                await queue.put((url_info, character_name, str(card_id), stars))

        except Exception as e:
            print(f"处理卡片 {card_id} 时出错: {str(e)}")

        # 添加短暂延迟，避免请求过于频繁
        await asyncio.sleep(1)


CARD_TOTAL = 1132


async def main():
    # 创建下载队列
    queue = Queue()

    # 创建 httpx 客户端，设置代理
    async with httpx.AsyncClient() as client:
        # 创建多个下载工作进程
        workers = []
        for _ in range(5):  # 5个并发下载进程
            worker = asyncio.create_task(download_worker(queue, client))
            workers.append(worker)

        # 启动生产者
        producer_task = asyncio.create_task(producer(queue, 1, CARD_TOTAL))

        # 等待生产者完成
        await producer_task

        # 等待队列清空
        await queue.join()

        # 取消所有工作进程
        for worker in workers:
            worker.cancel()

        # 等待所有工作进程完成
        await asyncio.gather(*workers, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
