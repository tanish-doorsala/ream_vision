"""
Bead width: camera + measurement + UI in one launch.

    ros2 launch vision_processor ream_vision_launch.py

Arguments (all optional):
    camera:=true|false       start the Spinnaker camera driver (default true)
    camera_type:=chameleon   camera family for the driver (default chameleon)
    serial:=16306023         camera serial number (default 16306023)
    roi:=746,176,621,520     x,y,width,height of the bead ROI (default: saved roi.yaml)
    pixels_per_mm:=38.9     scale; default 38.9 px/mm, the ruler reading; the ruler in view overrides it
    show_ui:=true|false      OpenCV windows (default true)

If the camera is already running in another terminal, stop it first or pass camera:=false.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    camera_driver = PathJoinSubstitution([
        FindPackageShare("spinnaker_camera_driver"),
        "launch",
        "driver_node.launch.py",
    ])

    return LaunchDescription([
        DeclareLaunchArgument("camera", default_value="true"),
        DeclareLaunchArgument("camera_type", default_value="chameleon"),
        DeclareLaunchArgument("serial", default_value="16306023"),
        DeclareLaunchArgument("roi", default_value="746,176,621,520"),
        DeclareLaunchArgument("pixels_per_mm", default_value="38.9"),
        DeclareLaunchArgument("show_ui", default_value="true"),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(camera_driver),
            launch_arguments={
                "camera_name": "flir_camera",
                "camera_type": LaunchConfiguration("camera_type"),
                "serial": LaunchConfiguration("serial"),
            }.items(),
            condition=IfCondition(LaunchConfiguration("camera")),
        ),

        Node(
            package="ream_vision",
            executable="bead_width",
            name="bead_width",
            output="screen",
            parameters=[{
                "image_topic": "/flir_camera/image_raw",
                "roi": LaunchConfiguration("roi"),  # "x,y,w,h" string, parsed by the node
                "pixels_per_mm": ParameterValue(LaunchConfiguration("pixels_per_mm"), value_type=float),
                "show_ui": ParameterValue(LaunchConfiguration("show_ui"), value_type=bool),
            }],
        ),
    ])
