from setuptools import find_packages, setup

package_name = 'ream_vision'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/ream_vision_launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='tanish',
    maintainer_email='your@email.com',
    description='Bead width measurement from the camera, with ROI tools.',
    license='MIT',
    entry_points={
        'console_scripts': [
            'bead_width = ream_vision.ream_vision_bead_width:main',
            'roi_grabber = ream_vision.ream_vision_roi_grabber:main',
            'roi_tuner = ream_vision.ream_vision_roi_tuner:main',
        ],
    },
)
