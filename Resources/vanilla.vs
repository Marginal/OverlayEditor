#version 120

uniform vec4 transform;	// x,y,z,hdg
attribute float skip;	// would prefer bool, but that requires GLSL 1.30
varying vec2 texcoord;

void main()
{
    float coshdg = cos(transform.w);
    float sinhdg = sin(transform.w);
    mat4 t;

    if (transform.y >= 0)
        t = mat4(coshdg, 0, sinhdg, 0,
                 0, 1, 0, 0,
                 -sinhdg, 0, coshdg, 0,
                 transform.x, transform.y, transform.z, 1);
    else
	// Defeat elevation data
        t = mat4(1, 0, 0, 0,
                 0, 0, 0, 0,
                 0, 0, 1, 0,
                 0, 0, 0, 1);

    gl_Position = gl_ProjectionMatrix * t * gl_Vertex;
    gl_Position.z += skip * 2 * gl_Position.w;	// send beyond far clipping plane
    gl_FrontColor = gl_BackColor = gl_Color;
    texcoord = vec2(gl_MultiTexCoord0.s, 1.0 - gl_MultiTexCoord0.t);	// Flip vertically
}
