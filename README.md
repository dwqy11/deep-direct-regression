# deep-direct-regression

### todo
- [ ]  loss / batch_size is strange (2017-07-19)
- [ ]  data augmentation 
    - [ ] [e.g. Kaggle Galaxy Zoo challenge](http://benanne.github.io/2014/04/05/galaxy-zoo.html)
    - [ ] [paper](https://arxiv.org/pdf/1503.07077.pdf)
        * 可视化了很多层，网络可视化做的不错，有时间读一下 
    - [x] ~~crop 320 * 320~~
    - [ ] crop from sacled image
    - [x] ~~rotate~~
- [ ] 网络参数初始化，有一次resume training, loss突然飘的特别高

### 2017年07月19日12:11:28
- [ ] ~~icdar2017 data augmentation~~
    - [ ] ~~rotate~~
- [ ] 学习keras fcn
    - [ ] 看看fcn的上采样的图, 有没有分块
    - [ ] fcn resume training 好用吗？
    - [ ] fcn的fit_generator与fit相比的训练速度


- [ ] Read paper: Fully Convolutional Networks for Semantic Segmentation
    - [ ] 什么叫做receptive fields 
        - [ ] Locations in higher layers correspond to the locations in the image they are path-connected to, which are called their receptive fields. 
    - [ ] we add skips between layers to fuse 
        * coarse  
        * semantic  
        * local   
        * appearance information
    - [ ] loss是什么？
        - [ ] per-pixel multinomial logistic loss
    - [ ] 最后是一个分类问题吗？把图片分为21类？？ 
- [ ] FCN-keras 实现
    1. padding的目的和作用,我大概明白了
        - [ ]
            ```
            a = np.ones((4, 3, 2))
            # npad is a tuple of (n_before, n_after) for each dimension
            npad = ((0, 0), (1, 2), (2, 1))
            b = np.pad(a, pad_width=npad, mode='constant', constant_values=0)

            [[[ 1 1 ]
              [ 1 1 ]
              [ 1 1 ]]
              [[ 1 1 ]
              [ 1 1 ]
              [ 1 1 ]]
              [[ 1 1 ]
              [ 1 1 ]
              [ 1 1 ]]]
            for dimension 1, (0, 0) 左边补充0个，右边补充0个
            for dimension 2, (1, 2) , 左边补充1个，右边补充2个
                                    [[1 1], [1 1], [1 1]]  --- > [[0 0], [1 1], [1 1], [1 1], [0 0], [0 0]]
                                    [[1 1], [1 1], [1 1]]  --- > [[0 0], [1 1], [1 1], [1 1], [0 0], [0 0]]
                                    [[1 1], [1 1], [1 1]]  --- > [[0 0], [1 1], [1 1], [1 1], [0 0], [0 0]]
            for dimension 3, (2, 1) [1 1], 左边补充1个，右边补充2个
                                    [0, 0] ---> [0, 0, 0, 0, 0]
                                    [1, 1] ---> [0, 0, 1, 1, 0]
                                    ..............
                                    [0, 0] ---> [0, 0, 0, 0, 0]
            ```
        - [ ] 先来看看np.pad是怎么使用的
            ```
            # do padding
            # convert x and y to array mode
            x = img_to_array(img, data_format=self.data_format)         # channels_last
            y = img_to_array(label, data_format=self.data_format).astype(int)
            img_w, img_h = img.size

            pad_w = max(self.target_size[1] - img_w, 0)             # 320 - 500
            pad_h = max(self.target_size[0] - img_h, 0)             # 320 - 375
            x = np.lib.pad(x, ((pad_h / 2, pad_h - pad_h / 2), (pad_w / 2, pad_w - pad_w / 2), (0, 0)), 'constant', constant_values=0.)
            y = np.lib.pad(y, ((pad_h / 2, pad_h - pad_h / 2), (pad_w / 2, pad_w - pad_w / 2), (0, 0)), 'constant', constant_values=self.label_cval)
            ```
            ![](https://github.com/yuayi521/deep-direct-regression/blob/master/png/1_.png)
            ![](https://github.com/yuayi521/deep-direct-regression/blob/master/png/2.png)

    2. Zero-center by mean pixel  
        ```
        x = x[:, :, :, ::-1]
        plt.subplot(221)
        print x[0, :, :, 0]
        plt.plot(np.arange(320 * 320), x[0, :, :, 0].flatten(), ".")
        # Zero-center by mean pixel
        # plt.subplot(222)
        x[:, :, :, 0] -= 103.939
        plt.plot(np.arange(320 * 320), x[0, :, :, 0].flatten(), ".")
        x[:, :, :, 1] -= 116.779
        x[:, :, :, 2] -= 123.68
        plt.show()
        ```
        ![](https://github.com/yuayi521/deep-direct-regression/blob/master/png/3_.png)

            * 把(320, 320)第一个通道的每个像素值都减去了103
            * 原来所有的像素值差不多是以255/2为中心，所有的像素值对称
            * zero-center by mean pixel之后是以0位中心，所有的像素值对称

### 2017-07-20 11:51:22


### Python 技巧
- [ ]
    - [ ] os.path.realpath(path)
        - [ ] Return the canonical(权威的) path of the specified filename, eliminating any symbolic links encountered in the path     
    - [ ] 在python下，获取当前执行主脚本的方法有两个：sys.argv[0]和 \_\_file\_\_
    ```   
    current_dir = os.path.dirname(os.path.realpath(__file__))   
    save_path = os.path.join(current_dir, 'Models/' + model_name_)   
    # I should learn this method   
    if os.path.exists(save_path) is False:   
        os.mkdir(save_path)   
    ```
- [ ] 关于[matplotlib](http://matplotlib.org/users/image_tutorial.html)，(好像还可以输出热点图heatmap，有时间仔细研究一下), python打印图片处理的库
    - [ ] png图片(320, 320, 1) 直接使用plt.imshow(y)，会报错，原因是应该把3维的数组，压缩为2维的
        * plt.imshow(y[:, :, 0])
        * plt.imshow(y.squeeze)

### Keras
- [ ] from keras.preprocessing.image import image, 这个图像预处理工具包，挺有用的
    - [ ] img_to_arr
    - [ ] arr_to_img
    - [ ] list_pictures
    - [ ] DirectoryIterators class
        - [ ] 迭代器，能从硬盘上读取图片
