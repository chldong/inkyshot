import os

inputFolder = "D:/Downloads/QWeather-Icons-1.1.1/icons"    #输入的文件夹，里面有svg
outputFolder = "D:/Downloads/QWeather-Icons-1.1.1/pngs"  #输出的文件夹，将把结果放到此文件夹中

for root, dirs, files in os.walk(inputFolder):#遍历所有的文件
    for f in files:
        svg_file = os.path.join(root,f)  #svg文件名
        if f[-3:] == "svg":#确保是svg           
            png_file = outputFolder + "/" + f.replace("svg","png") #png文件名
            # cairosvg.svg2png(url=svgFile, write_to=pngFile)

            resolution = 768
            from wand.api import library
            import wand.color
            import wand.image

            with open(svg_file,"r") as svg_file:
                with wand.image.Image() as image:
                    with wand.color.Color('transparent') as background_color:
                        library.MagickSetBackgroundColor(image.wand,
                                                        background_color.resource)
                    svg_blob = svg_file.read().encode('utf-8')
                    image.read(blob=svg_blob, resolution = resolution)
                    png_image = image.make_blob("png32")

            with open(png_file,"wb") as out:
                out.write(png_image)
